#!/usr/bin/env python3
"""
config/targets.yaml の目標一覧を表示する。

レビュー側（daily-review / weekly-review）から呼び出され、目標値の宣言だけを返す。
現在値や残差の算出はレビュー（AI）がレポートデータを見て判断する責務。

Usage:
    python scripts/show_targets.py
    python scripts/show_targets.py --interval weekly
    python scripts/show_targets.py --interval monthly
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

TARGETS_YAML = Path(__file__).resolve().parents[1] / "config" / "targets.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description="目標一覧を表示")
    parser.add_argument(
        "--interval",
        choices=["weekly", "monthly", "quarterly"],
        default=None,
        help="表示するreview頻度（未指定で全件）",
    )
    args = parser.parse_args()

    with TARGETS_YAML.open() as f:
        data = yaml.safe_load(f) or {}
    targets = data.get("targets", [])

    if args.interval:
        targets = [t for t in targets if t.get("review") == args.interval]

    if not targets:
        print(f"対象なし (interval={args.interval})")
        return 0

    print(f"## 目標一覧 ({args.interval or 'all'})\n")
    print("| key | target | unit | direction | review | note |")
    print("|---|---|---|---|---|---|")
    for t in targets:
        print(
            f"| {t['key']} | {t['target']} | {t.get('unit','')} | "
            f"{t['direction']} | {t['review']} | {t.get('note','')} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
