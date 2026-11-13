#!/usr/bin/env python
# coding: utf-8
"""
XOSS G+ サイコン CLI（fetch / import）

サイコン本体の FIT を data/xoss/fit/（dailybuild-private への symlink）に正本として置き、
走行の要約を data/xoss/rides.csv に1行=1ライドで upsert する。取り込みは本人が iiyama で
手動で行う（日次には入れない）。詳細は docs/xoss.md。

Usage:
    python scripts/xoss.py fetch          # BLE で本体の未取得 FIT を取り、rides.csv を更新する
    python scripts/xoss.py import <dir>   # 手元の FIT のディレクトリから取り込む
    python scripts/xoss.py import data/xoss/fit   # 保存済みの FIT から rides.csv を作り直す

取得ログは stderr（上流の print も stderr へ寄せる）。
サイズが一覧と合わない FIT・取れなかった FIT があれば保存せず非ゼロで終わる（次回取り直せる）。
"""

import argparse
import asyncio
import contextlib
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.xoss import fit_summary, store

log = logging.getLogger('xoss')


def _ingest(fit_paths: list[Path]) -> int:
    """FIT を保存（上書きしない）し、渡された全 FIT の要約を upsert する。保存した新規数を返す"""
    saved = sum(store.save_fit(p) for p in fit_paths)
    rows = [r for r in (fit_summary.summarize_file(p) for p in fit_paths) if r]
    if rows:
        df = store.upsert_rides(rows)
        log.info('rides.csv 更新: %s (総行数 %d行)', store.RIDES_CSV, len(df))
    return saved


def cmd_import(args) -> int:
    src = Path(args.dir)
    if not src.is_dir():
        sys.exit(f'⚠️ ディレクトリではない: {src}')
    paths = sorted(src.glob('*.fit'))
    if not paths:
        sys.exit(f'⚠️ FIT が無い: {src}')
    saved = _ingest(paths)
    log.info('FIT %d 件のうち新規保存 %d 件・既存 %d 件', len(paths), saved, len(paths) - saved)
    return 0


def cmd_fetch(args) -> int:
    from lib.xoss import ble_sync

    skip = store.existing_fit_names()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(sys.stderr):
        result = asyncio.run(ble_sync.fetch_files(Path(tmp), skip))
        if result is None:
            log.error('⚠️ サイコンに接続できなかった')
            return 1
        fetched, sizes = result

        failed = []
        good = []
        got = {p.name for p in fetched}
        for name in sorted(set(sizes) - skip):
            expected = sizes[name]
            if name not in got:
                failed.append(f'{name}: 取れなかった')
            elif expected is not None and (Path(tmp) / name).stat().st_size != expected:
                size = (Path(tmp) / name).stat().st_size
                failed.append(f'{name}: サイズ不一致 {size} != {expected}（保存しない）')
            else:
                good.append(Path(tmp) / name)
        if not sizes:
            failed.append('一覧が取れなかった')

        saved = _ingest(good) if good else 0
    log.info('一覧 %d 件: 新規保存 %d 件・取得済みで skip %d 件・失敗 %d 件',
             len(sizes), saved, len(set(sizes) & skip), len(failed))
    for msg in failed:
        log.error('⚠️ %s', msg)
    return 1 if failed else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)
    parser = argparse.ArgumentParser(description='XOSS G+ サイコン CLI')
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_fetch = subparsers.add_parser('fetch', help='BLE で本体の未取得 FIT を取り込む')
    p_fetch.set_defaults(func=cmd_fetch)

    p_import = subparsers.add_parser('import', help='ディレクトリの FIT を取り込む')
    p_import.add_argument('dir', help='*.fit を含むディレクトリ（data/xoss/fit でもよい）')
    p_import.set_defaults(func=cmd_import)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
