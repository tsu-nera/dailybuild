#!/usr/bin/env python
# coding: utf-8
"""
Tuya Cloud API クライアント（室内環境センサー）

Tuya のログ API には集計・リサンプル機能が無い。デバイスは値が変化しなくても
**1秒ごと**に送信するため（実測: 100件/33秒）、素直に全件取得すると1日約26万件・
約2,600コールになり日次バッチに載らない。

そこで `start_time`/`end_time` が任意に指定できることを使い、**一定間隔の境界ごとに
短い窓だけを引く**。1境界1コールで済み、5分刻みなら1日288コールに収まる。
窓の中の複数サンプルは平均する（点サンプリングより安定し、コール数は変わらない）。
"""

import datetime as dt
import json
import logging
import time
from pathlib import Path

import tinytuya

logger = logging.getLogger(__name__)

# 取得対象のDPコード → CSV列名。
# 実測で3項目とも scale=0（変換不要）。spec 側の scale を優先し、
# 取れなければこのフォールバックを使う。
CODE_TO_COLUMN = {
    'co2_value': 'co2_ppm',
    'temp_current': 'temperature',
    'humidity_value': 'humidity',
}
FALLBACK_SCALE = {
    'co2_value': 0,
    'temp_current': 0,
    'humidity_value': 0,
}

# 各境界で引く窓の幅（秒）。デバイスは1秒間隔なので60秒あれば十分なサンプル数になる。
WINDOW_SEC = 60

REPORT_LOGS_PATH = '/v2.0/cloud/thing/{device_id}/report-logs'
DEVICE_LOGS_PATH = '/v1.0/devices/{device_id}/logs'

# v1.0 logs の event type。7 = data report（デバイスからの計測値の報告）。
EVENT_TYPE_DATA_REPORT = 7

# API の size 上限。200 以上は Parameter error (40000303) になる。
MAX_PAGE_SIZE = 100


class TuyaError(RuntimeError):
    """Tuya API がエラーを返した（認証切れ・Trial失効・権限不足など）"""


class TuyaRateLimitError(TuyaError):
    """ログ照会のレート制限に当たった（リトライで回復しうる）"""


# ログ照会のレート制限。実測: 無待機は全滅、0.7秒だと数十回に一度 40000309 を踏んで
# バックオフに入る、1.5秒なら40回連続で失敗ゼロ。API 自体のレイテンシが約1.3秒あるので
# ここを詰めても速くならない。
MIN_REQUEST_INTERVAL = 1.5

# レート制限に当たったときの待機（秒）。使い切ったら諦めて落とす。
RATE_LIMIT_BACKOFF = (3, 10, 30, 60)

RATE_LIMIT_CODE = 40000309


def load_credentials(path: Path) -> dict:
    """認証情報を読む。未配置なら作成方法を案内して落とす。"""
    if not path.exists():
        raise TuyaError(
            f"認証情報がありません: {path}\n"
            f"  1. https://iot.tuya.com/ で Cloud Project を作成\n"
            f"  2. Devices → Link App Account で Smart Life アカウントを連携\n"
            f"  3. Overview の Access ID / Access Secret を控える\n"
            f"  4. {path.name}.sample をコピーして値を埋める"
        )
    creds = json.loads(path.read_text())
    missing = [k for k in ('api_region', 'api_key', 'api_secret', 'device_id')
               if not creds.get(k)]
    if missing:
        raise TuyaError(f"{path} に必須項目がありません: {missing}")
    return creds


def _check(response) -> dict:
    """Tuya の戻り値からエラーを検出する。

    tinytuya は失敗を例外にせず dict のまま返すので、ここで落とさないと
    「0件取得」として静かに欠測を捏造する。
    """
    if not isinstance(response, dict):
        raise TuyaError(f"予期しない応答: {response!r}")
    if response.get('Error'):
        raise TuyaError(f"Tuya API エラー: {response.get('Error')} "
                        f"{response.get('Payload', '')}")
    if not response.get('success', False):
        if response.get('code') == RATE_LIMIT_CODE:
            raise TuyaRateLimitError(f"レート制限: {response.get('msg')}")
        raise TuyaError(f"Tuya API エラー: code={response.get('code')} "
                        f"msg={response.get('msg')}")
    return response.get('result') or {}


class TuyaIndoorClient:
    """CO2/温度/湿度センサーからの取得に特化した Tuya Cloud クライアント"""

    def __init__(self, creds: dict):
        self.device_id = creds['device_id']
        self.cloud = tinytuya.Cloud(
            apiRegion=creds['api_region'],
            apiKey=creds['api_key'],
            apiSecret=creds['api_secret'],
            apiDeviceID=creds['device_id'],
        )
        # tinytuya は Cloud() の中でトークンを取りに行き、失敗しても例外を投げない
        if isinstance(self.cloud.token, dict) or not self.cloud.token:
            raise TuyaError(f"アクセストークンを取得できません: {self.cloud.token}")
        self._scales = None
        self._last_request = 0.0

    def _request(self, path: str, query: dict) -> dict:
        """スロットリングとレート制限リトライを噛ませた API 呼び出し"""
        for attempt, backoff in enumerate((0, *RATE_LIMIT_BACKOFF)):
            if backoff:
                logger.warning("レート制限。%d秒待って再試行 (%d/%d)",
                               backoff, attempt, len(RATE_LIMIT_BACKOFF))
                time.sleep(backoff)
            elapsed = time.monotonic() - self._last_request
            if elapsed < MIN_REQUEST_INTERVAL:
                time.sleep(MIN_REQUEST_INTERVAL - elapsed)
            self._last_request = time.monotonic()
            try:
                return _check(self.cloud.cloudrequest(path, query=query))
            except TuyaRateLimitError:
                continue
        raise TuyaRateLimitError(
            f"レート制限が解消しない（{len(RATE_LIMIT_BACKOFF)}回リトライ）。"
            f"時間をおいて再実行するか --interval-min を大きくする")

    def scales(self) -> dict:
        """DPコード → scale。spec が取れなければフォールバック定数を使う。"""
        if self._scales is not None:
            return self._scales
        scales = dict(FALLBACK_SCALE)
        try:
            result = _check(self.cloud.getproperties(self.device_id))
            for item in result.get('status', []):
                code = item.get('code')
                if code not in CODE_TO_COLUMN:
                    continue
                values = item.get('values')
                if isinstance(values, str):
                    values = json.loads(values)
                if isinstance(values, dict) and 'scale' in values:
                    scales[code] = int(values['scale'])
        except (TuyaError, ValueError, TypeError) as exc:
            logger.warning("spec を取得できないためフォールバックの scale を使う: %s", exc)
        self._scales = scales
        return scales

    def fetch_window(self, start: dt.datetime, width_sec: int = WINDOW_SEC,
                     codes: list[str] | None = None) -> list[dict]:
        """1つの窓の生ログを返す。空リストは「その時間帯にデータが無い」を意味する。

        codes を指定すると v2.0 report-logs で絞り込む（1コールあたりの件数が減る）。
        codes=None は v1.0 logs を使って全DPを引く（`--raw` のマッピング同定用）。
        report-logs は codes 必須で、省くと `illegal param (1110)` になる。
        """
        start_ms = int(start.timestamp() * 1000)
        end_ms = start_ms + width_sec * 1000
        logs = []
        last_row_key = None
        while True:
            query = {
                'start_time': start_ms,
                'end_time': end_ms,
                'size': MAX_PAGE_SIZE,
            }
            if codes:
                path = REPORT_LOGS_PATH.format(device_id=self.device_id)
                query['codes'] = ','.join(codes)
                if last_row_key:
                    query['last_row_key'] = last_row_key
            else:
                path = DEVICE_LOGS_PATH.format(device_id=self.device_id)
                query['type'] = EVENT_TYPE_DATA_REPORT
                if last_row_key:
                    query['start_row_key'] = last_row_key
            result = self._request(path, query)
            page = result.get('logs') or []
            logs.extend(page)
            has_more = result.get('has_more', result.get('has_next'))
            if not has_more or not page:
                break
            last_row_key = result.get('last_row_key')
            if not last_row_key:
                break
        return logs

    def sample_window(self, start: dt.datetime, width_sec: int = WINDOW_SEC) -> dict | None:
        """窓内のサンプルを平均して1点にする。データが無ければ None。

        None は欠測を意味する。呼び出し側で前後から補間してはいけない
        （デバイスがオフラインだった時間帯と区別できなくなる）。
        """
        logs = self.fetch_window(start, width_sec, codes=list(CODE_TO_COLUMN))
        if not logs:
            return None

        scales = self.scales()
        buckets: dict[str, list[float]] = {}
        for entry in logs:
            code = entry.get('code')
            if code not in CODE_TO_COLUMN:
                continue
            try:
                value = float(entry.get('value'))
            except (TypeError, ValueError):
                continue
            buckets.setdefault(code, []).append(value / (10 ** scales[code]))

        if not buckets:
            return None
        row = {'datetime': start.replace(tzinfo=None)}
        for code, column in CODE_TO_COLUMN.items():
            values = buckets.get(code)
            row[column] = round(sum(values) / len(values), 1) if values else None
        return row

    def raw_codes(self, start: dt.datetime, width_sec: int = 300) -> dict:
        """`--raw` 用。窓内に出現した code とその値のサンプルを返す。"""
        samples: dict[str, list] = {}
        for entry in self.fetch_window(start, width_sec, codes=None):
            samples.setdefault(entry.get('code'), []).append(entry.get('value'))
        return samples
