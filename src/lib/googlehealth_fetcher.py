#!/usr/bin/env python
# coding: utf-8
"""
Google Health データ取得・保存処理

Fitbit Web API 廃止に伴い、data/wearable/*.csv を更新する唯一の経路になっている。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from .clients import googlehealth_client
from .utils import csv_utils
from .utils.private_data import ensure_dir

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / 'data' / 'wearable'
GOOGLEHEALTH_DIR = BASE_DIR / 'data' / 'googlehealth'

# この日付より前は Google 側が値を再計算しており、Fitbit 由来の既存 CSV と一致しない
# （HRV で ±0.2〜3.0ms、呼吸数で ±0.2〜0.8/min）。うっかり長期間を指定すると
# 履歴が静かに書き換わるため、既定では書き込みを拒否する。方針決定は Issue #50。
HISTORY_BOUNDARY = dt.date(2026, 6, 1)

# 値が既存 CSV と完全一致することを実測で確認済みのエンドポイントのみ（Issue #49）。
# heart_rate / spo2 は Issue #78 で対応（heart_rate はプラットフォーム選択、
# spo2 は日付ラベルの1日ずれを睡眠セッションの引き当てで解決）。
#
# sleep は他と違い:
#   - 'kind': 'period_replace' -> 期間置換（logId 空間が Fitbit と Google で
#     別物のため、キーマージではなく取得期間の既存行を丸ごと置換する。
#     src/lib/utils/csv_utils.py:replace_csv_period の docstring 参照）
#   - 'extra_csv': sleep.csv に加えて sleep_levels.csv も同じ戦略で書く
#   - date_column が index にならない（logId 系と同じく複数行/日があるため）
#
# default_days（--days 未指定時の取得窓）はエンドポイントの種類でコストが
# 3段に分かれるため、種類ごとに揃える（Issue #70/#125）:
#   - dailyRollUp 型（activity, active_zone_minutes）: 14日まではコストゼロ。
#     googlehealth_client.ROLLUP_MAX_DURATION_DAYS['total-calories'] == 14 が
#     全 rollup 型の中で最も狭く、この上限までは1チャンクで収まるため
#     2日窓でも14日窓でもリクエスト数は変わらない。15日以上にして初めて
#     total-calories がチャンク分割され、コストが増える。だから既定は14。
#   - daily list 型（hrv 等7種）: 1日あたり1〜数点でページングも増えず、
#     窓を広げてもコストはほぼゼロ。
#   - intraday 型（*_intraday）: 分刻みサンプルのためページ数が日数にほぼ
#     線形に増える（2日で約79ページ・約57秒を実測）。現状維持で2日のまま。
# daily-routine.sh が毎日 --days 2 の一律窓で叩いていたことが根本原因
# （実行が失敗した日は窓の外に落ち、二度と再取得されない）。rollup と
# daily list は窓を広げてもコストが変わらないので、その分は既定を広げて
# 部分日の取り直しを保証する。
ENDPOINTS = {
    'hrv': {
        'description': 'HRV（心拍変動）',
        'date_column': 'date',
        'default_days': 7,
    },
    'breathing_rate': {
        'description': '呼吸数',
        'date_column': 'date',
        'default_days': 7,
    },
    'temperature_skin': {
        'description': '皮膚温（睡眠中）',
        'date_column': 'date',
        'default_days': 7,
    },
    'heart_rate': {
        'description': '安静時心拍数',
        'date_column': 'date',
        'default_days': 7,
    },
    'spo2': {
        'description': 'SpO2（血中酸素飽和度）',
        'date_column': 'date',
        'default_days': 7,
    },
    'sleep': {
        'description': '睡眠',
        'date_column': 'dateOfSleep',
        'kind': 'period_replace',
        'extra_csv': 'sleep_levels',
        'default_days': 7,
    },
    'activity': {
        'description': '活動量（歩数・距離・活動時間・消費カロリー）',
        'date_column': 'date',
        'default_days': 14,
    },
    'active_zone_minutes': {
        'description': 'アクティブゾーン分',
        'date_column': 'date',
        'default_days': 14,
    },
    # 実測時刻の行と日次固定00:00:00の行が混在するため、キーマージではなく
    # sleep と同じ期間置換にする（src/lib/clients/googlehealth_client.py の
    # fetch_temperature_core docstring 参照）
    # 体温計で測って Google Health に手で記録するもので、自動計測ではない。
    # 測り忘れる日があるのが常態（通算31件、月0〜12件）なので0件をエラーにしない。
    # allow_empty にする前は測らなかった日すべてで daily-routine.sh が非ゼロ終了し、
    # 「Google Health の取得に失敗」と毎日出ていた（実際は測っていないだけ）
    'temperature_core': {
        'description': '深部体温',
        'date_column': 'date_time',
        'kind': 'period_replace',
        'allow_empty': True,
        'default_days': 7,
    },
    # 1日に複数行が立つセッション型。既存の Fitbit CSV を書き換えないよう
    # data/googlehealth/ に別ファイルとして持つ（activity_logs.csv との
    # スキーマ統一は Issue #77 の担当）。日付でなく id でマージするため
    # HISTORY_BOUNDARY の対象外
    'exercise': {
        'description': '運動セッション',
        'date_column': 'start',
        'merge_key': 'id',
        'output': GOOGLEHEALTH_DIR / 'exercise.csv',
        'columns': googlehealth_client.EXERCISE_COLUMNS,
        'default_days': 7,
    },
    # カフェインを飲まなかった/記録していない期間は0件が正常状態（allow_empty）。
    # 他のエンドポイントと違い、0件をエラーにしない（Issue #90）
    'caffeine': {
        'description': 'カフェイン摂取',
        'date_column': 'time',
        'merge_key': 'id',
        'output': GOOGLEHEALTH_DIR / 'caffeine.csv',
        'columns': googlehealth_client.CAFFEINE_COLUMNS,
        'allow_empty': True,
        'default_days': 7,
    },
    # Fitbit 由来ではない（2025 以降は HealthPlanet アプリが Health Connect に
    # 書いたもの）。既存の data/wearable/body_weight.csv とはスキーマを揃えられない
    # ため（bmi が返らない、logId 空間が別物）別ファイルにする。
    # 体組成の計測は数日〜週おきで疎なので、短い窓では0件が正常状態（allow_empty）
    'weight': {
        'description': '体重',
        'date_column': 'time',
        'merge_key': 'id',
        'output': GOOGLEHEALTH_DIR / 'weight.csv',
        'columns': googlehealth_client.WEIGHT_COLUMNS,
        'allow_empty': True,
        'default_days': 7,
    },
    'body_fat': {
        'description': '体脂肪率',
        'date_column': 'time',
        'merge_key': 'id',
        'output': GOOGLEHEALTH_DIR / 'body_fat.csv',
        'columns': googlehealth_client.BODY_FAT_COLUMNS,
        'allow_empty': True,
        'default_days': 7,
    },
    # nutrition-log は個別食事ログしか持たない（日次サマリのデータ型は存在しない）。
    # nutrition.csv はログの合算で作る。water は取得元のデータ型が無いので常に空欄。
    # 食事記録は現在ほぼ行われておらず、短い窓では0件が正常状態なので allow_empty
    # にする（0件をエラーにすると daily-routine.sh が常時失敗する）
    'nutrition': {
        'description': '栄養（日次サマリ）',
        'date_column': 'date',
        'allow_empty': True,
        'default_days': 7,
    },
    'nutrition_logs': {
        'description': '栄養（個別食事ログ）',
        'date_column': 'logDate',
        'merge_key': 'logId',
        'columns': googlehealth_client.NUTRITION_LOG_COLUMNS,
        'allow_empty': True,
        'default_days': 7,
    },
    # intraday 5種（Issue #76）。merge_key は付けない（= 日付インデックスの
    # merge_csv 経路）。HISTORY_BOUNDARY のガードは merge_key 無しの経路に
    # そのまま効くため、バックフィルは allow_history_rewrite 明示時のみ。
    #
    # heart_rate_intraday だけ exclude_from_all: 生サンプルは1日約33,000点=
    # 約660ページ=約8分かかり、fetch_all に含めると日次運用が壊れる。
    # `--endpoint heart_rate_intraday` で明示指定したときだけ取る
    # （docs/googlehealth.md「intraday」節参照）。
    'heart_rate_intraday': {
        'description': '心拍数（分刻み）',
        'date_column': 'datetime',
        'exclude_from_all': True,
        'default_days': 2,
    },
    'steps_intraday': {
        'description': '歩数（分刻み）',
        'date_column': 'datetime',
        'default_days': 2,
    },
    'spo2_intraday': {
        'description': 'SpO2（分刻み）',
        'date_column': 'datetime',
        'default_days': 2,
    },
    'hrv_intraday': {
        'description': 'HRV（分刻み）',
        'date_column': 'datetime',
        'default_days': 2,
    },
    'br_intraday': {
        'description': '呼吸数（睡眠、日次）',
        'date_column': 'date',
        'default_days': 2,
    },
}


def get_output_path(endpoint: str) -> Path:
    config = ENDPOINTS.get(endpoint, {})
    return config.get('output') or DATA_DIR / f'{endpoint}.csv'


def list_endpoints() -> list[str]:
    return list(ENDPOINTS.keys())


def fetch_endpoint(creds, endpoint: str, days: int = None, overwrite: bool = False,
                   start_date: dt.date = None, end_date: dt.date = None,
                   allow_history_rewrite: bool = False) -> dict:
    """
    指定エンドポイントを Google Health API から取得して CSV に保存する

    Args:
        creds: googlehealth_client.authorize() の戻り値
        endpoint: ENDPOINTS のキー
        days: 取得日数（start_date 未指定時のみ有効）
        overwrite: True なら既存 CSV を置き換える。False ならマージ
        start_date: 開始日（指定時は days を無視）
        end_date: 終了日（未指定時は今日）
        allow_history_rewrite: HISTORY_BOUNDARY より前を取得して既存値を
                               上書きすることを許可する

    Returns:
        {'records': 件数, 'path': 保存先, 'error': エラーメッセージ}
    """
    if endpoint not in ENDPOINTS:
        raise ValueError(
            f'Unknown endpoint: {endpoint}. Available: {list(ENDPOINTS.keys())}'
        )

    config = ENDPOINTS[endpoint]
    # 呼び出し側が明示した days は従来通り最優先。未指定（None）なら
    # エンドポイント種別ごとの default_days を使う（ハードコードした一律14を廃止）。
    # ENDPOINTS の全エントリが default_days を持つ前提で bracket access する
    # （.get() で握り潰すと、窓の設定漏れが黙って0件を招く）
    default_days = config['default_days']
    start_date, end_date = _resolve_range(days, start_date, end_date, default_days)

    if start_date < HISTORY_BOUNDARY and not config.get('merge_key') \
            and not allow_history_rewrite:
        msg = (
            f'{start_date} は履歴境界 {HISTORY_BOUNDARY} より前。'
            'この範囲は Google と Fitbit で値が異なり、既存CSVを書き換えてしまう。'
            '意図的に行うなら allow_history_rewrite=True を指定すること（Issue #50）'
        )
        print(f'  ⚠️ {msg}')
        return {'records': 0, 'path': None, 'error': msg}

    print(f"{config['description']}を取得中... ({start_date} ~ {end_date})")

    try:
        result = googlehealth_client.FETCHERS[endpoint](creds, start_date, end_date)
    except googlehealth_client.GoogleHealthError as e:
        print(f'  エラー: {e}')
        return {'records': 0, 'path': None, 'error': str(e)}

    if config.get('kind') == 'period_replace':
        return _save_period_replace(endpoint, config, result, start_date, end_date, overwrite)

    rows = result
    if not rows:
        if config.get('allow_empty'):
            # 0件は正常でありうるが、取得の故障とは区別できない旨だけ警告する
            # （例: カフェインを飲まなかった/記録していない期間）
            msg = f'{start_date}〜{end_date} のデータが0件。正常な場合もあるが取得の故障とは区別できない'
            print(f'  ⚠️ {msg}')
            return {'records': 0, 'path': None}
        # 取得系の沈黙故障と区別できないため、空を成功として扱わない
        msg = f'{start_date}〜{end_date} のデータが0件。Google側に無いか取得が壊れている'
        print(f'  ⚠️ {msg}')
        return {'records': 0, 'path': None, 'error': msg}

    date_col = config['date_column']
    merge_key = config.get('merge_key')
    df = pd.DataFrame(rows, columns=config.get('columns'))

    out_path = get_output_path(endpoint)
    ensure_dir(out_path.parent)

    if merge_key:
        # セッション型は1日に複数行が立つので、日付ではなく id でマージする。
        # id は19桁の整数。dtype=str を明示しないと読み戻しで int になり
        # 新旧のキーが一致せず、同じセッションが二重に残る
        df[merge_key] = df[merge_key].astype(str)
        if not overwrite and out_path.exists():
            df_old = pd.read_csv(out_path, dtype={merge_key: str})
            df = pd.concat([df_old, df]).drop_duplicates(
                subset=[merge_key], keep='last').sort_values(date_col)
        df.to_csv(out_path, index=False)
    else:
        df[date_col] = pd.to_datetime(df[date_col])
        df.set_index(date_col, inplace=True)
        if not overwrite:
            df = csv_utils.merge_csv(df, out_path, date_col)
        df.to_csv(out_path)
    print(f'  保存: {out_path} ({len(df)}件)')
    return {'records': len(df), 'path': out_path}


def _save_period_replace(endpoint: str, config: dict, result, start_date: dt.date,
                         end_date: dt.date, overwrite: bool) -> dict:
    """
    キーマージが成立しないエンドポイントの保存経路: 期間置換で書く
    （csv_utils.replace_csv_period）

    sleep のように 'extra_csv' を持つ型は、fetcher が (主CSV行, 付随CSV行) の
    タプルを返す。それ以外（temperature_core 等）は行リストをそのまま返す。

    overwrite=True の場合は期間置換ではなく、取得した行だけで CSV 全体を
    置き換える（他エンドポイントの overwrite と挙動を揃える）
    """
    if config.get('extra_csv'):
        rows, extra_rows = result
    else:
        rows, extra_rows = result, None
    if not rows:
        if config.get('allow_empty'):
            msg = f'{start_date}〜{end_date} のデータが0件。正常な場合もあるが取得の故障とは区別できない'
            print(f'  ⚠️ {msg}')
            return {'records': 0, 'path': None}
        msg = f'{start_date}〜{end_date} のデータが0件。Google側に無いか取得が壊れている'
        print(f'  ⚠️ {msg}')
        return {'records': 0, 'path': None, 'error': msg}

    date_col = config['date_column']
    out_path = get_output_path(endpoint)
    ensure_dir(out_path.parent)

    df = pd.DataFrame(rows)
    if overwrite:
        df.to_csv(out_path, index=False)
    else:
        df = csv_utils.replace_csv_period(
            df, out_path, date_col, start_date, end_date, sort_by=[date_col],
            label=endpoint,
        )
        df.to_csv(out_path, index=False)
    print(f'  保存: {out_path} ({len(df)}件)')
    result_dict = {'records': len(df), 'path': out_path}

    extra_key = config.get('extra_csv')
    if extra_key:
        extra_out_path = get_output_path(extra_key)
        ensure_dir(extra_out_path.parent)
        df_extra = pd.DataFrame(extra_rows)
        if overwrite:
            df_extra.to_csv(extra_out_path, index=False)
        else:
            df_extra = csv_utils.replace_csv_period(
                df_extra, extra_out_path, date_col, start_date, end_date,
                sort_by=[date_col], label=extra_key,
            )
            df_extra.to_csv(extra_out_path, index=False)
        print(f'  保存: {extra_out_path} ({len(df_extra)}件)')
        result_dict[extra_key] = {'records': len(df_extra), 'path': extra_out_path}

    return result_dict


def fetch_all(creds, days: int = None, overwrite: bool = False,
              start_date: dt.date = None, end_date: dt.date = None,
              allow_history_rewrite: bool = False) -> dict:
    """対応済みエンドポイントをまとめて取得する

    'exclude_from_all' が立っているエンドポイント（heart_rate_intraday）は
    スキップする。fetch_endpoint での明示指定では取れる。
    """
    results = {}
    for endpoint, config in ENDPOINTS.items():
        if config.get('exclude_from_all'):
            continue
        results[endpoint] = fetch_endpoint(
            creds, endpoint, days=days, overwrite=overwrite,
            start_date=start_date, end_date=end_date,
            allow_history_rewrite=allow_history_rewrite,
        )
    return results


def _resolve_range(days, start_date, end_date, default_days) -> tuple[dt.date, dt.date]:
    if start_date is not None:
        return start_date, end_date or dt.date.today()
    days = days or default_days
    end = dt.date.today()
    return end - dt.timedelta(days=days - 1), end
