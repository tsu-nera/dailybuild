#!/usr/bin/env python3
"""
目標進捗の表示スクリプト

config/targets.yaml の数値目標を読み込み、現在値・残差・達成状況を表示する。
daily-review / weekly-review から呼ばれる。

Usage:
    python scripts/show_targets.py                  # 全件
    python scripts/show_targets.py --interval weekly
    python scripts/show_targets.py --interval monthly
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.lib.targets import evaluate


def fmt_value(v, unit: str) -> str:
    if v is None:
        return "-"
    if isinstance(v, float) and v.is_integer():
        return f"{int(v)}{unit}"
    return f"{v}{unit}"


def main() -> int:
    parser = argparse.ArgumentParser(description="目標進捗を表示")
    parser.add_argument(
        "--interval",
        choices=["weekly", "monthly", "quarterly"],
        default=None,
        help="表示する目標のreview頻度（未指定で全件）",
    )
    args = parser.parse_args()

    results = evaluate(interval=args.interval)
    if not results:
        print(f"対象なし (interval={args.interval})")
        return 0

    title = f"目標進捗 ({args.interval or 'all'})"
    print(f"## {title}\n")
    print("| key | interval | target | current | 残り | 達成 | 期間 |")
    print("|---|---|---|---|---|---|---|")
    for r in results:
        s = r.spec
        target = fmt_value(s.target, s.unit)
        current = fmt_value(r.current, s.unit)
        remaining = fmt_value(round(r.remaining, 2) if r.remaining is not None else None, s.unit)
        if r.achieved is None:
            achieved = "-"
        else:
            achieved = "✅" if r.achieved else "⏳"
        print(f"| {s.key} | {s.review} | {target} | {current} | {remaining} | {achieved} | {r.period_label} |")

    # 詳細メモ
    details = [r for r in results if r.detail]
    if details:
        print("\n### 詳細")
        for r in details:
            print(f"- **{r.spec.key}**: {r.detail}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
