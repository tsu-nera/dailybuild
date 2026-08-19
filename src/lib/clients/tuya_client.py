"""Tuya Cloud API クライアント（CO2モニター向け）

LSENLTY WiFi CO2モニター（Tuya/Smart Life系デバイス）から、Tuya Cloud API 経由で
過去のデバイスログ（CO2・温度・湿度）を取得する。LAN ローカル接続（tinytuya.Device）は
未対応。Device Log Service は無料枠で過去7日分しか保持しない恒久的な仕様（Trialの制限ではない。
それ以上遡るには年額USD 1,500〜の有料プランが必要）のため、日次バッチでの差分蓄積が必須となる。

これとは別に、Cloud Project 自体の Trial アカウントは1ヶ月で期限切れし、これも API エラーの
要因になりうる（両者は無関係な別の制限）。
"""

import datetime as dt
import json
import logging

import pandas as pd
import tinytuya

logger = logging.getLogger(__name__)

JST = dt.timezone(dt.timedelta(hours=9))

# Tuya の DP コード → CSV 列名 とフォールバックのスケール（値をこの数で割る）。
# コードもスケールも機種依存。実機で確定させるには `--raw` を使うこと。
# 複数エイリアスを持たせているのは機種差をある程度吸収する意図。実機未確認のため暫定。
DP_CODE_MAP = {
    'co2_value':      {'column': 'co2_ppm',     'scale': 1},
    'co2':            {'column': 'co2_ppm',     'scale': 1},
    'temp_current':   {'column': 'temperature', 'scale': 10},
    'va_temperature': {'column': 'temperature', 'scale': 10},
    'humidity_value':  {'column': 'humidity',    'scale': 1},
    'va_humidity':     {'column': 'humidity',    'scale': 1},
}

CSV_COLUMNS = ['co2_ppm', 'temperature', 'humidity']

# Device Log Service の無料枠が保持する最大日数（恒久的な仕様。Trial期限切れとは別問題）
CLOUD_LOG_MAX_DAYS = 7


class TuyaCloudError(Exception):
    """Tuya Cloud API がエラーを返した場合の例外"""


def _check_error(result):
    """tinytuya の Cloud API レスポンスをエラーチェックする

    tinytuya の Cloud API は失敗時に例外を投げず
    ``{'Error': ..., 'Err': ..., 'Payload': ...}`` の形で返す。
    すべての API 呼び出しの戻り値をこれに通すこと。

    Parameters
    ----------
    result : dict
        tinytuya.Cloud の各メソッドの戻り値

    Returns
    -------
    dict
        result をそのまま返す（チェーン用）

    Raises
    ------
    TuyaCloudError
        result がエラーを表す場合
    """
    if isinstance(result, dict) and 'Error' in result:
        err = result.get('Err')
        msg = result.get('Error')
        raise TuyaCloudError(f"Tuya Cloud API エラー (Err={err}): {msg}")
    return result


def create_cloud(creds: dict) -> tinytuya.Cloud:
    """認証情報から tinytuya.Cloud インスタンスを作成する

    Parameters
    ----------
    creds : dict
        api_region / api_key / api_secret / device_id を持つ辞書

    Returns
    -------
    tinytuya.Cloud
    """
    return tinytuya.Cloud(
        apiRegion=creds['api_region'],
        apiKey=creds['api_key'],
        apiSecret=creds['api_secret'],
        apiDeviceID=creds['device_id'],
    )


def resolve_scales(cloud: tinytuya.Cloud, device_id: str) -> dict[str, float]:
    """デバイスの spec からコードごとのスケール除数を取得する

    Tuya の spec では `values` フィールドが JSON 文字列で入っており、その中に
    ``"scale": 1`` のような整数が入っている。scale は10の冪指数で、
    実値 = 生値 / 10**scale となる。

    getproperties のレスポンス構造は機種・APIバージョンで揺れるため、
    パースに失敗しても例外を投げず空 dict を返す（フォールバックは呼び出し側の
    DP_CODE_MAP に委ねる）。プロパティが取れなくてもログ取得自体は続行できるため、
    ここだけは _check_error で落とさず warning ログに留める。

    Parameters
    ----------
    cloud : tinytuya.Cloud
    device_id : str

    Returns
    -------
    dict[str, float]
        {code: 除数}。取得・パース失敗時は空 dict
    """
    try:
        result = cloud.getproperties(device_id)
    except Exception as e:
        logger.warning("getproperties の呼び出しに失敗: %s", e)
        return {}

    if isinstance(result, dict) and 'Error' in result:
        logger.warning("getproperties がエラーを返した: %s", result.get('Error'))
        return {}

    scales: dict[str, float] = {}
    try:
        status = result.get('result', {}).get('status', [])
        for prop in status:
            code = prop.get('code')
            values_raw = prop.get('values')
            if not code or not values_raw:
                continue
            values = json.loads(values_raw) if isinstance(values_raw, str) else values_raw
            scale = values.get('scale') if isinstance(values, dict) else None
            if scale is not None:
                scales[code] = float(10 ** int(scale))
    except Exception as e:
        logger.warning("getproperties のパースに失敗: %s", e)
        return {}

    return scales


def _jst_date_to_epoch(d: dt.date, end_of_day: bool = False) -> int:
    """JST の日付境界を unix epoch 秒に変換する"""
    if end_of_day:
        t = dt.time(23, 59, 59)
    else:
        t = dt.time(0, 0, 0)
    ts = dt.datetime.combine(d, t, tzinfo=JST)
    return int(ts.timestamp())


def fetch_device_log(cloud: tinytuya.Cloud, device_id: str,
                      start: dt.date, end: dt.date) -> list[dict]:
    """指定期間のデバイスログ（event type 7 = data report）を取得する

    Cloud API は最大1週間しか遡れない。要求期間が7日を超える場合は
    warning を出す（エラーにはしない）。

    Parameters
    ----------
    cloud : tinytuya.Cloud
    device_id : str
    start, end : datetime.date
        取得期間（両端を含む）。JST の日付境界で epoch 秒に変換して渡す

    Returns
    -------
    list[dict]
        ログエントリのリスト（各要素は event_time(ms) / code / value 等を持つ）
    """
    if (end - start).days + 1 > CLOUD_LOG_MAX_DAYS:
        logger.warning(
            "要求期間が%d日を超えている（%s ～ %s）。Tuya Cloud APIは最大%d日分しか遡れない",
            CLOUD_LOG_MAX_DAYS, start, end, CLOUD_LOG_MAX_DAYS,
        )

    start_epoch = _jst_date_to_epoch(start, end_of_day=False)
    end_epoch = _jst_date_to_epoch(end, end_of_day=True)

    result = cloud.getdevicelog(device_id, start=start_epoch, end=end_epoch,
                                 evtype='7', size=0)
    _check_error(result)

    return result.get('result', {}).get('logs', [])


def logs_to_dataframe(logs: list[dict], scales: dict[str, float] | None = None,
                       interval_min: int = 5) -> pd.DataFrame:
    """デバイスログを CSV 用 DataFrame に変換する

    Parameters
    ----------
    logs : list[dict]
        fetch_device_log() が返すログエントリのリスト
    scales : dict[str, float] | None
        resolve_scales() が返すコードごとの除数。該当コードが無ければ
        DP_CODE_MAP のフォールバック値を使う
    interval_min : int
        resample する間隔（分）

    Returns
    -------
    pd.DataFrame
        列 ['datetime', 'co2_ppm', 'temperature', 'humidity']。
        datetime は JST tz-naive の '%Y-%m-%d %H:%M:%S' 文字列
    """
    scales = scales or {}
    out_columns = ['datetime'] + CSV_COLUMNS

    if not logs:
        return pd.DataFrame(columns=out_columns)

    rows = []
    for log in logs:
        code = log.get('code')
        mapping = DP_CODE_MAP.get(code)
        if mapping is None:
            continue

        try:
            value = float(log.get('value'))
        except (TypeError, ValueError):
            continue

        event_time_ms = log.get('event_time')
        if event_time_ms is None:
            continue
        ts = pd.Timestamp(int(event_time_ms), unit='ms', tz='UTC').tz_convert(JST).tz_localize(None)

        divisor = scales.get(code, mapping['scale'])
        rows.append({
            'datetime': ts,
            'column': mapping['column'],
            'value': value / divisor,
        })

    if not rows:
        return pd.DataFrame(columns=out_columns)

    df = pd.DataFrame(rows)
    # 同一タイムスタンプ・同一列の重複は平均でよい
    pivoted = df.pivot_table(index='datetime', columns='column', values='value', aggfunc='mean')

    resampled = pivoted.resample(f'{interval_min}min').mean()
    # 全列が NaN の行は落とす（デバイスが offline の時間帯に空行を作らない）
    resampled = resampled.dropna(how='all')

    for col in CSV_COLUMNS:
        if col not in resampled.columns:
            resampled[col] = pd.NA
    resampled = resampled[CSV_COLUMNS]
    resampled.columns.name = None

    resampled = resampled.reset_index()
    resampled['datetime'] = resampled['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')

    return resampled[out_columns]


def summarize_raw_logs(logs: list[dict]) -> str:
    """生ログを DP コード同定用に人間可読な文字列にまとめる（--raw 用）

    Parameters
    ----------
    logs : list[dict]
        fetch_device_log() が返すログエントリのリスト

    Returns
    -------
    str
        code ごとの出現件数・値のサンプル・DP_CODE_MAP に載っているかをまとめたテキスト
    """
    if not logs:
        return "ログが0件です。"

    by_code: dict[str, list] = {}
    for log in logs:
        code = log.get('code', '(unknown)')
        by_code.setdefault(code, []).append(log.get('value'))

    lines = [f"検出された code: {len(by_code)}種類 / ログ総数: {len(logs)}件", '']
    for code, values in sorted(by_code.items()):
        known = code in DP_CODE_MAP
        mapping_info = (
            f"→ column={DP_CODE_MAP[code]['column']}, fallback_scale={DP_CODE_MAP[code]['scale']}"
            if known else "→ DP_CODE_MAP未登録"
        )
        samples = values[:3]
        lines.append(f"- {code}: {len(values)}件 サンプル={samples} {mapping_info}")

    return '\n'.join(lines)
