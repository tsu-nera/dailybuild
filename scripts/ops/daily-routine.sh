#!/bin/bash
# 日次取得の入口（vaio 専用）。timer（毎日12:00）と /reviewing-health daily の ssh 起動から呼ばれる。
# /reviewing-health weekly は本スクリプトと weekly-routine.sh を順に呼ぶ。
#
# private を pull → daily-fetch.sh → commit → pull --rebase → push の順に回す（scripts/ops/lib/routine.sh）。
# daily-fetch.sh が途中で失敗しても取れたソースのデータは正しいので、commit・push は行い、
# 終了コードは daily-fetch.sh のものを返す。rebase が衝突したら abort して非ゼロで止まる
# （強制 push はしない）。同じ衝突は次回も起きるので、解消は人が行う。それまでの
# 取得はローカルに commit され続け、窓の短いソースも欠測にならない。
#
# Usage:
#   scripts/ops/daily-routine.sh --days 7   # 引数は daily-fetch.sh へそのまま渡す
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=lib/routine.sh
source "$REPO/scripts/ops/lib/routine.sh"

# FETCH の上書きはテストでスタブに差し替えるためだけにある
routine_entry daily "${DAILYBUILD_FETCH:-$REPO/scripts/ops/daily-fetch.sh}" "$@"
