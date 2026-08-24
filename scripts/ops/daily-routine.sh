#!/bin/bash
# 日次のデータ取得をまとめて実行する。判断は一切せず、副作用だけを起こす。
#
# 途中で失敗しても後続を止めない（Fitbit が落ちても体組成・家計簿は取りに行く）。
# ただし黙って成功扱いにはせず、失敗したステップ名を最後にまとめて出し、
# 非ゼロで終了する。cron から回す場合もログに残る。
#
# Usage:
#   scripts/ops/daily-routine.sh            # 直近2日
#   scripts/ops/daily-routine.sh --days 7
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

DAYS=2
while [ $# -gt 0 ]; do
  case "$1" in
    --days) DAYS="$2"; shift 2 ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done

LOG_DIR="logs/daily-routine"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/$(date +%Y-%m-%d).log") 2>&1

FAILED=()

# 失敗しても後続を続ける。ステップ名を控えて最後に報告する
step() {
  local name="$1"; shift
  echo ""
  echo ">>> $name"
  if ! "$@"; then
    echo "!!! $name に失敗（後続は続行する）"
    FAILED+=("$name")
  fi
}

echo "=== Daily Routine (--days $DAYS) ==="
echo "Started at $(date)"

step "Fitbit"        uv run python scripts/fetch_fitbit.py --all --days "$DAYS"
step "HealthPlanet"  uv run python scripts/fetch_healthplanet.py
step "日出・日入"     uv run python scripts/fetch_sun_times.py --days 14
step "気象"          uv run python scripts/fetch_weather.py --days 14
step "手動記録"       uv run python scripts/fetch_manual.py
step "Toggl"         uv run python scripts/toggl.py fetch --days "$DAYS"
step "Toggl反映"      uv run python scripts/toggl.py push --days "$DAYS"
# 一括更新のキックは完了を待たない。取り込まれた明細は翌日の実行で回収される
step "MoneyForward"  uv run python scripts/fetch_mf.py --refresh

echo ""
echo "Finished at $(date)"

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "=== 失敗した取得: ${FAILED[*]} ==="
  exit 1
fi

echo "=== Daily Routine Complete ==="
