#!/usr/bin/env python
# coding: utf-8
"""
行動イベントの正規化ストリーム CLI（build）

Toggl・運動・睡眠・Habitica の行動系 CSV を、時刻を tz-aware（JST）に揃えた
1行1イベントの reports/events.jsonl へまとめる。全上書きの派生物なので
data/ には置かない（あちらは取得の正本）。

Usage:
    python scripts/events.py build

ソース別の件数は stderr に出す。期待するソースのいずれかが 0 件なら
そのソース名を出して非ゼロ終了し、events.jsonl は更新しない。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.events import build
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).parent.parent
EVENTS_JSONL = BASE_DIR / 'reports' / 'events.jsonl'


def cmd_build(args) -> int:
    require_private_path(BASE_DIR / 'data')
    out_path = require_private_path(EVENTS_JSONL)

    by_source = build.collect(build.SourcePaths.default(BASE_DIR))
    for name, events in by_source.items():
        print(f'{name}: {len(events)}件', file=sys.stderr)

    empty = build.empty_sources(by_source)
    if empty:
        print(f'エラー: 0件のソースがあるため events.jsonl を更新しない: {", ".join(empty)}',
              file=sys.stderr)
        return 1

    events = build.merge(by_source)
    build.write_jsonl(events, out_path)
    print(f'{len(events)}件 -> {out_path}', file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='行動イベントの正規化ストリーム')
    sub = parser.add_subparsers(dest='command', required=True)
    p_build = sub.add_parser('build', help='reports/events.jsonl を全上書きで生成する')
    p_build.set_defaults(func=cmd_build)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
