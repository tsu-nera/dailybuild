#!/bin/bash
# vaio で走る日次取得のラッパー。timer（12:00）と /daily-review の ssh 起動の両方から呼ばれる。
#
# private を pull → daily-routine.sh → commit → pull --rebase → push の順に回す。
# routine が途中で失敗しても取れたソースのデータは正しいので、commit・push は行い、
# 終了コードは routine のものを返す。rebase が衝突したら abort して非ゼロで止まる
# （強制 push はしない）。同じ衝突は次回も起きるので、解消は人が行う。それまでの
# 取得はローカルに commit され続け、窓の短いソースも欠測にならない。
#
# Usage:
#   scripts/ops/scheduled-routine.sh --days 7   # 引数は daily-routine.sh へそのまま渡す
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE="${DAILYBUILD_PRIVATE:-$HOME/repo/dailybuild-private}"
# ROUTINE の上書きはテストでスタブに差し替えるためだけにある
ROUTINE="${DAILYBUILD_ROUTINE:-$REPO/scripts/ops/daily-routine.sh}"

# timer と ssh 起動が重なったら、後から来た方を断る
exec 9>"$PRIVATE/.git/dailybuild-routine.lock" || exit 1
if ! flock -n 9; then
  echo "別の実行が進行中のため中止する" >&2
  exit 75
fi

# pull に失敗しても取得は止めない。git の問題で取得を止めると、Toggl のように
# 窓の短いソースが欠測になる。rebase 途中の状態だけは残さない
if ! git -C "$PRIVATE" pull --rebase; then
  git -C "$PRIVATE" rebase --abort 2>/dev/null
  echo "警告: private の pull --rebase に失敗。取得は続け、ローカルに commit する" >&2
fi

OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT
"$ROUTINE" "$@" 2>&1 | tee "$OUT"
RC=${PIPESTATUS[0]}

git -C "$PRIVATE" add -A
if ! git -C "$PRIVATE" diff --cached --quiet; then
  MSG="data: daily routine $(date '+%Y-%m-%d %H:%M')"
  FAILED="$(sed -n 's/^=== 失敗した取得: \(.*\) ===$/\1/p' "$OUT" | tail -n 1)"
  [ -n "$FAILED" ] && MSG="$MSG (failed: $FAILED)"
  if ! git -C "$PRIVATE" commit -q -m "$MSG"; then
    echo "エラー: private の commit に失敗" >&2
    exit 1
  fi
fi

# 差分が無くても、前回の衝突で push できなかった commit が残りうるので毎回 push する
if ! git -C "$PRIVATE" pull --rebase; then
  git -C "$PRIVATE" rebase --abort 2>/dev/null
  echo "エラー: rebase が衝突したため中断した。ローカル commit は残してある（強制 push はしない）" >&2
  exit 1
fi
if ! git -C "$PRIVATE" push; then
  echo "エラー: private の push に失敗" >&2
  exit 1
fi

exit "$RC"
