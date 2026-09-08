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

# link <リポジトリ内のパス> [private 側のパス（省略時は同名）]
link() {
  local dst="$1" src="${2:-$1}"
  # 実体ディレクトリが残っていると symlink が中に作られてしまうので拒否する
  if [ -e "$DAILYBUILD/$dst" ] && [ ! -L "$DAILYBUILD/$dst" ]; then
    echo "エラー: $DAILYBUILD/$dst が実体として存在します。private へ退避してから再実行してください" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$DAILYBUILD/$dst")"
  ln -sfn "$PRIVATE/$src" "$DAILYBUILD/$dst"
  printf '  %-14s -> %s\n' "$dst" "$PRIVATE/$src"
}

echo "非公開データの symlink を作成:"
link data
link reports
link config/private config
echo "完了"
