#!/usr/bin/env bash
# 非公開データ（dailybuild-private）への symlink を張る。
# 新マシンや git worktree でのセットアップ時に一度だけ実行する。
# 冪等。既存の symlink は張り直す。
set -euo pipefail

DAILYBUILD="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE="${DAILYBUILD_PRIVATE:-$HOME/repo/dailybuild-private}"

if [ ! -d "$PRIVATE/.git" ]; then
  echo "エラー: dailybuild-private が見つかりません: $PRIVATE" >&2
  echo "  git clone git@github.com:tsu-nera/dailybuild-private.git \"$PRIVATE\"" >&2
  echo "  （別の場所に置く場合は DAILYBUILD_PRIVATE を設定）" >&2
  exit 1
fi

link() {
  mkdir -p "$(dirname "$DAILYBUILD/$1")"
  ln -sfn "$PRIVATE/$1" "$DAILYBUILD/$1"
  printf '  %-20s -> %s\n' "$1" "$PRIVATE/$1"
}

echo "非公開データの symlink を作成:"
link data/mf
link data/toggl
link data/emotion.csv
link reports/cbt
echo "完了"
