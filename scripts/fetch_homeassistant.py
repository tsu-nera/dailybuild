#!/usr/bin/env python
# coding: utf-8
"""
Home Assistant の statistics（5分値）と state 履歴の取得スクリプト

室温・湿度・照度などの5分値と、on/off・文字列・位置などの state 履歴を HA の
WebSocket API から取り、それぞれ月別 CSV に保存する。
詳細は docs/indoor.md。取得対象は config/homeassistant.yaml。

Usage:
    uv run python scripts/fetch_homeassistant.py              # 保存済みの最終時刻 -1h から（種類ごと）
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
from lib import homeassistant_state_store as state_store
from lib import homeassistant_store as store

BASE_DIR = Path(__file__).parent.parent
CONFIG_FILE = BASE_DIR / 'config' / 'homeassistant.yaml'

OVERLAP = dt.timedelta(hours=1)
CHUNK = dt.timedelta(days=7)
# これ以上の窓で1行も返らない entity は故障とみなす
EMPTY_GUARD_WINDOW = dt.timedelta(hours=1)


def load_config() -> dict:
    with open(CONFIG_FILE, encoding='utf-8') as f:
        return yaml.safe_load(f)


def parse_entities(items: list) -> dict[str, list[str]]:
    """yaml の entities 節を {entity_id: 保存する attributes のキー} へ。

    要素は entity_id の文字列か {entity_id, attributes} のマッピング
    """
    entities = {}
    for item in items or []:
        if isinstance(item, str):
            entities[item] = []
        else:
            entities[item['entity_id']] = list(item.get('attributes') or [])
    return entities


def resolve_start(latest: dt.datetime | None, now: dt.datetime, days: int,
                  since: str | None) -> dt.datetime:
    if since:
        return dt.datetime.strptime(since, '%Y-%m-%d').replace(tzinfo=store.JST)
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


def fetch_states_window(client, start: dt.datetime, end: dt.datetime,
                        entities: dict[str, list[str]]) -> tuple[pd.DataFrame, dict[str, int]]:
    """7日ごとに区切って state 履歴を取得する。(保存する行, entity ごとの応答行数) を返す

    応答行数は開始時点の state（保存しない行）も数える。存在する entity なら必ず1以上
    """
    frames = []
    returned = {eid: 0 for eid in entities}
    cur = start
    while cur < end:
        nxt = min(cur + CHUNK, end)
        result = client.history_during_period(cur, nxt, list(entities), attributes=True)
        for eid, states in result.items():
            returned[eid] = returned.get(eid, 0) + len(states)
        frames.append(state_store.to_dataframe(result, entities, cur))
        cur = nxt
    df = (pd.concat(frames, ignore_index=True) if frames
          else state_store.to_dataframe({}, entities, start))
    return df, returned


def run_states(client, base_dir: Path, entities: dict[str, list[str]], start: dt.datetime,
               end: dt.datetime) -> int:
    """state 履歴を取得・保存して終了コードを返す。HA が返した行だけを書く（補間しない）"""
    print(f"Home Assistant state 履歴: {start:%Y-%m-%d %H:%M} ～ {end:%Y-%m-%d %H:%M} (JST)",
          file=sys.stderr)
    df, returned = fetch_states_window(client, start, end, entities)
    written = state_store.save(df, base_dir)

    counts = df['entity_id'].value_counts() if not df.empty else {}
    for eid in entities:
        print(f"  {eid}: {int(counts.get(eid, 0))}行", file=sys.stderr)
    for path in written:
        print(f"  保存: {path}", file=sys.stderr)

    # 開始時点の state を含めて取るので、存在する entity は変化0回でも1行は返る
    missing = [eid for eid in entities if returned.get(eid, 0) == 0]
    if missing:
        print(f"エラー: 1行も返らなかった entity: {', '.join(missing)}"
              "（entity_id の誤り、または HA 側で記録されていない）", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Home Assistant statistics・state 履歴取得')
    parser.add_argument('--days', '-d', type=int, default=30,
                        help='保存済みデータが無いときの遡り日数')
    parser.add_argument('--since', type=str, help='開始日（YYYY-MM-DD、JST）')
    args = parser.parse_args()

    try:
        url, token = load_settings()
        client = HomeAssistantClient(url, token)
        config = load_config()
        now = dt.datetime.now(store.JST)
        start = resolve_start(store.latest_start(BASE_DIR), now, args.days, args.since)
        code = run(client, BASE_DIR, config['statistic_ids'], start, now)
        entities = parse_entities(config.get('entities'))
        if entities:
            start = resolve_start(state_store.latest_time(BASE_DIR), now, args.days, args.since)
            code = max(code, run_states(client, BASE_DIR, entities, start, now))
        return code
    except HomeAssistantError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
