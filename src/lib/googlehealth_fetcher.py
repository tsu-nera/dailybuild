#!/usr/bin/env python
# coding: utf-8
"""
Google Health データ取得・保存処理

fitbit_fetcher と同じ CSV（data/fitbit/*.csv）を同じスキーマで更新する。
Fitbit Web API 廃止（2026年9月）後は fitbit_fetcher を削除し、こちらに一本化する。

fitbit_fetcher に相乗りさせず別モジュールにしているのは、移行完了時に
fitbit_fetcher をファイルごと削除できるようにするため。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from .clients import googlehealth_api
from .utils import csv_utils
from .utils.private_data import ensure_dir

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / 'data' / 'fitbit'

# この日付より前は Google 側が値を再計算しており、Fitbit 由来の既存 CSV と一致しない
# （HRV で ±0.2〜3.0ms、呼吸数で ±0.2〜0.8/min）。うっかり長期間を指定すると
# 履歴が静かに書き換わるため、既定では書き込みを拒否する。方針決定は Issue #50。
HISTORY_BOUNDARY = dt.date(2026, 6, 1)

# 値が既存 CSV と完全一致することを実測で確認済みのエンドポイントのみ（Issue #49）。
# spo2 は未解決の定義差があるため未対応。
#
# sleep は他と違い:
#   - 'kind': 'period_replace' -> 期間置換（logId 空間が Fitbit と Google で
#     別物のため、キーマージではなく取得期間の既存行を丸ごと置換する。
#     src/lib/utils/csv_utils.py:replace_csv_period の docstring 参照）
#   - 'extra_csv': sleep.csv に加えて sleep_levels.csv も同じ戦略で書く
#   - date_column が index にならない（logId 系と同じく複数行/日があるため）
ENDPOINTS = {
    'hrv': {
        'description': 'HRV（心拍変動）',
        'date_column': 'date',
    },
    'breathing_rate': {
        'description': '呼吸数',
        'date_column': 'date',
    },
    'temperature_skin': {
        'description': '皮膚温（睡眠中）',
        'date_column': 'date',
    },
    'sleep': {
        'description': '睡眠',
        'date_column': 'dateOfSleep',
        'kind': 'period_replace',
        'extra_csv': 'sleep_levels',
    },
}


def get_output_path(endpoint: str) -> Path:
    return DATA_DIR / f'{endpoint}.csv'


def list_endpoints() -> list[str]:
    return list(ENDPOINTS.keys())


def fetch_endpoint(creds, endpoint: str, days: int = None, overwrite: bool = False,
                   start_date: dt.date = None, end_date: dt.date = None,
                   allow_history_rewrite: bool = False) -> dict:
    """
    指定エンドポイントを Google Health API から取得して CSV に保存する

    Args:
        creds: googlehealth_api.authorize() の戻り値
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
    start_date, end_date = _resolve_range(days, start_date, end_date)

    if start_date < HISTORY_BOUNDARY and not allow_history_rewrite:
        msg = (
            f'{start_date} は履歴境界 {HISTORY_BOUNDARY} より前。'
            'この範囲は Google と Fitbit で値が異なり、既存CSVを書き換えてしまう。'
            '意図的に行うなら allow_history_rewrite=True を指定すること（Issue #50）'
        )
        print(f'  ⚠️ {msg}')
        return {'records': 0, 'path': None, 'error': msg}

    print(f"{config['description']}を取得中... ({start_date} ~ {end_date})")

    try:
        result = googlehealth_api.FETCHERS[endpoint](creds, start_date, end_date)
    except googlehealth_api.GoogleHealthError as e:
        print(f'  エラー: {e}')
        return {'records': 0, 'path': None, 'error': str(e)}

    if config.get('kind') == 'period_replace':
        return _save_period_replace(endpoint, config, result, start_date, end_date, overwrite)

    rows = result
    if not rows:
        # 取得系の沈黙故障と区別できないため、空を成功として扱わない
        msg = f'{start_date}〜{end_date} のデータが0件。Google側に無いか取得が壊れている'
        print(f'  ⚠️ {msg}')
        return {'records': 0, 'path': None, 'error': msg}

    date_col = config['date_column']
    df = pd.DataFrame(rows)
    df[date_col] = pd.to_datetime(df[date_col])
    df.set_index(date_col, inplace=True)

    out_path = get_output_path(endpoint)
    ensure_dir(out_path.parent)

    if not overwrite:
        df = csv_utils.merge_csv(df, out_path, date_col)

    df.to_csv(out_path)
    print(f'  保存: {out_path} ({len(df)}件)')
    return {'records': len(df), 'path': out_path}


def _save_period_replace(endpoint: str, config: dict, result, start_date: dt.date,
                         end_date: dt.date, overwrite: bool) -> dict:
    """
    sleep 用の保存経路: 1回の取得で得た (主CSV行, 付随CSV行) を
    それぞれ期間置換で書く（csv_utils.replace_csv_period）

    overwrite=True の場合は期間置換ではなく、取得した行だけで CSV 全体を
    置き換える（他エンドポイントの overwrite と挙動を揃える）
    """
    rows, extra_rows = result
    if not rows:
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
                sort_by=[date_col],
            )
            df_extra.to_csv(extra_out_path, index=False)
        print(f'  保存: {extra_out_path} ({len(df_extra)}件)')
        result_dict[extra_key] = {'records': len(df_extra), 'path': extra_out_path}

    return result_dict


def fetch_all(creds, days: int = None, overwrite: bool = False,
              start_date: dt.date = None, end_date: dt.date = None,
              allow_history_rewrite: bool = False) -> dict:
    """対応済みエンドポイントをまとめて取得する"""
    results = {}
    for endpoint in ENDPOINTS:
        results[endpoint] = fetch_endpoint(
            creds, endpoint, days=days, overwrite=overwrite,
            start_date=start_date, end_date=end_date,
            allow_history_rewrite=allow_history_rewrite,
        )
    return results


def _resolve_range(days, start_date, end_date) -> tuple[dt.date, dt.date]:
    if start_date is not None:
        return start_date, end_date or dt.date.today()
    days = days or 14
    end = dt.date.today()
    return end - dt.timedelta(days=days - 1), end
