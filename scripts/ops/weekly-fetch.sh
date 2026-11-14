#!/bin/bash
# 週次の処理。直接は呼ばず、入口の weekly-routine.sh（flock → pull → 本スクリプト → commit・push）経由で回す。
# vaio だけが走らせる。
#
# 週次に置いてよいのは「遅れても次回に追いつき、データが消えないもの」だけ。
# 取得元の保持期間が短いもの（Toggl、Tuya の7日など）や、review の判断材料になるものは日次に残す。
# 今は Dawarich の2つ（data/ の軌跡を派生 DB へ上げる・UI で直した Place を data/ へ写す）だけで、
# Dawarich が動く mouse は使っていないと寝るため、日次では毎朝 timeout まで待って失敗していた。
#
# 起動は手動の /reviewing-health weekly から。timer にしないのは、mouse のような寝る機械が
# その時刻に起きている保証が無く、起こせなければ週に1度の機会を失うため。
#
# Usage:
#   scripts/ops/weekly-fetch.sh
set -uo pipefail

# shellcheck source=lib/routine.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/routine.sh"
routine_fetch_init weekly

echo "=== Weekly Routine ==="
echo "Started at $(date)"

# wake-mouse は dailybuild の外（~/repo/scripts）にあり、mouse が ping に答えるまで最大30秒待つ。
# 起こせなければ Dawarich は timeout まで待つだけなので、実行せずに失敗として出す
if step "mouse を起こす" "$HOME/repo/scripts/wake-mouse"; then
  step "Dawarich 軌跡"  uv run python scripts/dawarich.py import-routes
  step "Dawarich 場所"  uv run python scripts/dawarich.py capture-places
else
  echo "!!! mouse が起きないため Dawarich 軌跡・Dawarich 場所 をスキップした（次回に追いつく）"
  FAILED+=("Dawarich 軌跡" "Dawarich 場所")
fi

routine_fetch_finish "Weekly Routine"
