#!/bin/bash
# 週次処理の入口（vaio 専用）。本人がいる /reviewing-health weekly（gtd）が daily-routine.sh の後に ssh で呼ぶ。
# timer では回さない（中身が mouse を起こすので、本人が近くにいるときに回す。理由は weekly-fetch.sh）。
#
# private を pull → weekly-fetch.sh → commit → pull --rebase → push の順に回す。挙動は daily-routine.sh と同じで
# （scripts/ops/lib/routine.sh）、lock も共有するので日次と同時には走らない。
#
# Usage:
#   scripts/ops/weekly-routine.sh
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=lib/routine.sh
source "$REPO/scripts/ops/lib/routine.sh"

# FETCH の上書きはテストでスタブに差し替えるためだけにある
routine_entry weekly "${DAILYBUILD_WEEKLY_FETCH:-$REPO/scripts/ops/weekly-fetch.sh}" "$@"
