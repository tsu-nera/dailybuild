#!/usr/bin/env python3
"""認知再構成エントリーの索引・集計。

エントリー（frontmatter + 散文）が正本で、INDEX.md はここから毎回全生成する。
手で追記しない（append 忘れが黙って集計から落ちるため）。
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

try:  # C 実装があると frontmatter の読み込みが8倍速い（1100件で 2.5s → 0.3s）
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.utils.private_data import require_private_path  # noqa: E402

ENTRY_DIR = require_private_path(BASE_DIR / 'reports' / 'cognitive-restructuring')

DISTORTIONS = [
    '全か無か思考', '一般化のしすぎ', '心のフィルター', 'プラスの否認', '結論への飛躍',
    '拡大解釈と過小評価', '感情的決めつけ', 'べき思考', 'レッテル貼り', '個人化と自己批難',
]

HEADER = """# 認知再構成 索引

**生成物。手で編集しない**（`uv run scripts/cbt.py index` が全上書きする）。
正本は各エントリーの frontmatter で、この表はその射影。

- エントリー `YYYY-MM-DD-NN.md` … 1セッション1ファイル。追記・上書きしない
- 恒久的に効く知見（歪みのクセ・手法の当たり外れ・本人の体質）はここではなく **memory** に置く
- **動き** 欄は感情強度と自動思考の確信度の再評価。数字が動かなかった記録は失敗ではなく、
  自動思考が**事実の核**に当たったシグナル。認知の再構成で動くのは「事実 → 結論」の接続部分だけ
"""


def load_entries():
    entries = []
    for path in sorted(ENTRY_DIR.glob('20??-??-??-??.md')):
        text = path.read_text(encoding='utf-8')
        if not text.startswith('---\n'):
            raise ValueError(f'frontmatter がない: {path.name}')
        fm = yaml.load(text.split('---\n', 2)[1], Loader=SafeLoader)
        entries.append((path, fm))
    return entries


def movement(fm):
    if fm.get('exclude'):
        return fm.get('movement_note') or '—'
    parts = []
    for e in fm.get('emotions') or []:
        if e.get('before') is not None and e.get('after') is not None:
            parts.append(f"{e['label']}{e['before']}→{e['after']}")
    tc = fm.get('thought_confidence') or {}
    if tc.get('before') is not None and tc.get('after') is not None:
        parts.append(f"確信{tc['before']}→{tc['after']}")
    if fm.get('change'):
        parts.append(f"{fm['change']}（{fm['mode']}、強度は取らず）")
    note = fm.get('movement_note')
    if note:
        parts.append(note)
    return '。'.join(parts) if parts else '—'


def build_index(entries):
    lines = [HEADER, '\n| 日付 | ファイル | 状況 | 中心の歪み | 動き |', '|---|---|---|---|---|']
    for path, fm in sorted(entries, key=lambda x: x[0].name, reverse=True):
        stem = path.stem
        label = stem[5:]
        dist = ' / '.join((fm.get('distortions') or [])[:2]) or '—'
        lines.append(
            f"| {label[:5]} | [{label}]({path.name}) | {fm['summary']} | {dist} | {movement(fm)} |"
        )
    return '\n'.join(lines) + '\n'


def build_jsonl(entries):
    """jq / pandas / duckdb がそのまま食える派生。正本は frontmatter。"""
    lines = []
    for path, fm in sorted(entries, key=lambda x: x[0].name):
        lines.append(json.dumps({'file': path.name, **fm}, ensure_ascii=False, default=str))
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=['index'])
    ap.add_argument('--check', action='store_true', help='書き換えず、最新かどうかだけ見る')
    args = ap.parse_args()

    entries = load_entries()
    outputs = {
        ENTRY_DIR / 'INDEX.md': build_index(entries),
        ENTRY_DIR / 'entries.jsonl': build_jsonl(entries),
    }
    if args.check:
        stale = [p.name for p, c in outputs.items()
                 if (p.read_text(encoding='utf-8') if p.exists() else '') != c]
        if stale:
            print(f'{", ".join(stale)} が古い。`uv run scripts/cbt.py index` を実行すること',
                  file=sys.stderr)
            return 1
        print('生成物は最新')
        return 0
    for path, content in outputs.items():
        path.write_text(content, encoding='utf-8')
    print(f'{" ".join(p.name for p in outputs)} ({len(entries)} entries)', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
