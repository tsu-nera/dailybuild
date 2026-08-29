#!/usr/bin/env python
# coding: utf-8
"""Habitica（習慣管理）

日付をまたぐ処理（Habitica 用語で cron）を毎日確定させる。Daily の未完了は
この処理でしか history に記録されないため、走らせない日は「未達」ではなく
「欠測」になり、達成率の分母が作れない。

Usage:
    python scripts/habitica.py cron     # cron を確定させ、実行を記録する
    python scripts/habitica.py status   # 現在の状態を表示（何も変更しない）

詳細と落とし穴は docs/habitica.md を参照。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import logging

import pandas as pd

from lib.clients.habitica_client import HabiticaClient, HabiticaError
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config' / 'habitica_creds.json'
CRON_LOG = BASE_DIR / 'data' / 'habitica' / 'cron_log.csv'

COLUMNS = [
    'date', 'ran_at', 'last_cron_prev', 'last_cron_get', 'needs_cron',
    'cron_posted', 'last_cron_final', 'hp', 'lvl', 'exp', 'gp',
]

logger = logging.getLogger(__name__)


def habitica_date(now: dt.datetime, day_start_hour: int) -> dt.date:
    """Habitica 上の「その日」を返す。dayStart（既定5時）より前は前日扱い。"""
    return (now - dt.timedelta(hours=day_start_hour)).date()


def load_cron_log() -> pd.DataFrame:
    if not CRON_LOG.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(CRON_LOG, dtype={'date': str})


def save_cron_log(df: pd.DataFrame, row: dict) -> pd.DataFrame:
    """同じ date の行は上書きする（同日に複数回走らせても重複させない）"""
    df = df[df['date'] != row['date']] if not df.empty else df
    merged = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    merged = merged[COLUMNS].sort_values('date').reset_index(drop=True)
    ensure_dir(CRON_LOG.parent)
    merged.to_csv(CRON_LOG, index=False)
    return merged


def run_cron(client: HabiticaClient) -> dict:
    """cron を確定させ、1行ぶんの記録を返す"""
    log = load_cron_log()
    last_cron_prev = log['last_cron_final'].iloc[-1] if not log.empty else ''

    user = client.get_user()
    day_start = int(user.get('preferences', {}).get('dayStart', 0))
    last_cron_get = user.get('lastCron', '')
    needs_cron = bool(user.get('needsCron'))

    if needs_cron:
        after = client.run_cron()
        last_cron_final = after.get('user', after).get('lastCron', last_cron_get)
        stats = after.get('user', after).get('stats', user.get('stats', {}))
    else:
        last_cron_final = last_cron_get
        stats = user.get('stats', {})

    now = dt.datetime.now()
    row = {
        'date': habitica_date(now, day_start).isoformat(),
        'ran_at': now.replace(microsecond=0).isoformat(),
        'last_cron_prev': last_cron_prev,
        'last_cron_get': last_cron_get,
        'needs_cron': needs_cron,
        'cron_posted': needs_cron,
        'last_cron_final': last_cron_final,
        'hp': round(float(stats.get('hp', 0)), 2),
        'lvl': stats.get('lvl'),
        'exp': stats.get('exp'),
        'gp': round(float(stats.get('gp', 0)), 2),
    }
    save_cron_log(log, row)
    return row


def cmd_cron(_args) -> int:
    require_private_path(CRON_LOG)
    client = HabiticaClient.from_config(CREDS_FILE)
    row = run_cron(client)

    if row['cron_posted']:
        print(f"cron を実行しました（{row['last_cron_get']} → {row['last_cron_final']}）")
    elif row['last_cron_prev'] and row['last_cron_get'] != row['last_cron_prev']:
        # 前回の記録より進んでいるのに needsCron が False。GET だけで走ったか、
        # 人がアプリを開いて走らせたか。どちらでも分母は積まれている
        print(f"cron は既に実行済み（{row['last_cron_prev']} → {row['last_cron_get']}）")
    else:
        print(f"cron の実行は不要（lastCron={row['last_cron_get']}）")

    print(f"{row['date']}  HP={row['hp']} Lv{row['lvl']} exp={row['exp']} gp={row['gp']}")
    print(f"記録: {CRON_LOG}")
    return 0


def cmd_status(_args) -> int:
    client = HabiticaClient.from_config(CREDS_FILE)
    user = client.get_user()
    stats = user.get('stats', {})
    prefs = user.get('preferences', {})
    print(f"lastCron   : {user.get('lastCron')}")
    print(f"needsCron  : {user.get('needsCron')}")
    print(f"dayStart   : {prefs.get('dayStart')}  timezoneOffset: {prefs.get('timezoneOffset')}")
    print(f"stats      : HP={stats.get('hp'):.1f} Lv{stats.get('lvl')} "
          f"exp={stats.get('exp')} gp={stats.get('gp'):.1f} class={stats.get('class')}")

    dailys = client.get_tasks('dailys')
    print(f"\nDailies ({len(dailys)}件)")
    for t in dailys:
        mark = '✔' if t.get('completed') else ('・' if t.get('isDue') else '-')
        print(f"  {mark} {t['text'][:24]:26} value={t['value']:>7.2f} "
              f"streak={t.get('streak', 0)} isDue={t.get('isDue')}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    parser = argparse.ArgumentParser(description='Habitica')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('cron', help='cron を確定させ、実行を記録する')
    sub.add_parser('status', help='現在の状態を表示する')
    args = parser.parse_args()

    handlers = {'cron': cmd_cron, 'status': cmd_status}
    try:
        return handlers[args.command](args)
    except HabiticaError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
