#!/usr/bin/env python
# coding: utf-8
"""
Home Assistant の statistics（5分値）取得スクリプト

室温・湿度・照度などを HA の WebSocket API から取り、月別 CSV に保存する。
詳細は docs/indoor.md。取得対象は config/homeassistant.yaml。

Usage:
    uv run python scripts/fetch_homeassistant.py              # 保存済みの最終時刻 -1h から
    uv run python scripts/fetch_homeassistant.py --days 30    # 初回の遡り日数
    uv run python scripts/fetch_homeassistant.py --since 2026-10-01
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt

import pandas as pd
import yaml

from lib.clients.homeassistant_client import (
    HomeAssistantClient,
    HomeAssistantError,
    load_settings,
)
from lib import homeassistant_store as store

BASE_DIR = Path(__file__).parent.parent
CONFIG_FILE = BASE_DIR / 'config' / 'homeassistant.yaml'

OVERLAP = dt.timedelta(hours=1)
CHUNK = dt.timedelta(days=7)
# これ以上の窓で1行も返らない entity は故障とみなす
EMPTY_GUARD_WINDOW = dt.timedelta(hours=1)


def load_statistic_ids() -> list[str]:
    with open(CONFIG_FILE, encoding='utf-8') as f:
        return yaml.safe_load(f)['statistic_ids']


def resolve_start(base_dir: Path, now: dt.datetime, days: int, since: str | None) -> dt.datetime:
    if since:
        return dt.datetime.strptime(since, '%Y-%m-%d').replace(tzinfo=store.JST)
    latest = store.latest_start(base_dir)
    if latest is not None:
        return latest.replace(tzinfo=store.JST) - OVERLAP
    return now - dt.timedelta(days=days)


def fetch_window(client, start: dt.datetime, end: dt.datetime,
                 statistic_ids: list[str]) -> pd.DataFrame:
    """7日ごとに区切って取得し、縦持ち DataFrame を返す"""
    frames = []
    cur = start
    while cur < end:
        nxt = min(cur + CHUNK, end)
        result = client.statistics_during_period(cur, nxt, statistic_ids)
        frames.append(store.to_dataframe(result))
        cur = nxt
    return pd.concat(frames, ignore_index=True) if frames else store.to_dataframe({})


def run(client, base_dir: Path, statistic_ids: list[str], start: dt.datetime,
        end: dt.datetime) -> int:
    """取得・保存して終了コードを返す。HA が返した行だけを書く（補間しない）"""
    print(f"Home Assistant 取得: {start:%Y-%m-%d %H:%M} ～ {end:%Y-%m-%d %H:%M} (JST)",
          file=sys.stderr)
    df = fetch_window(client, start, end, statistic_ids)
    written = store.save(df, base_dir)

    counts = df['entity_id'].value_counts() if not df.empty else {}
    for sid in statistic_ids:
        print(f"  {sid}: {int(counts.get(sid, 0))}行", file=sys.stderr)
    for path in written:
        print(f"  保存: {path}", file=sys.stderr)

    if end - start >= EMPTY_GUARD_WINDOW:
        empty = [sid for sid in statistic_ids if int(counts.get(sid, 0)) == 0]
        if empty:
            print(f"エラー: 1行も返らなかった entity: {', '.join(empty)}"
                  "（entity_id の誤り、または HA 側で記録が止まっている）", file=sys.stderr)
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Home Assistant statistics 取得')
    parser.add_argument('--days', '-d', type=int, default=30,
                        help='保存済みデータが無いときの遡り日数')
    parser.add_argument('--since', type=str, help='開始日（YYYY-MM-DD、JST）')
    args = parser.parse_args()

    try:
        url, token = load_settings()
        client = HomeAssistantClient(url, token)
        now = dt.datetime.now(store.JST)
        start = resolve_start(BASE_DIR, now, args.days, args.since)
        return run(client, BASE_DIR, load_statistic_ids(), start, now)
    except HomeAssistantError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
