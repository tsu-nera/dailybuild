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

# data/ reports/ は dailybuild-private への symlink。未設定のまま走らせると
# 各スクリプトが public 側にディレクトリを作り、既存データを見失う。
for d in data reports; do
  if [ ! -L "$d" ] || [ ! -d "$d" ]; then
    echo "エラー: $d が dailybuild-private にマウントされていません" >&2
    echo "  ./scripts/setup_private_links.sh を実行してください" >&2
    exit 1
  fi
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

step "Google Health" uv run python scripts/fetch_googlehealth.py --days "$DAYS" --non-interactive
step "HealthPlanet"  uv run python scripts/fetch_healthplanet.py
step "日出・日入"     uv run python scripts/fetch_sun_times.py --days 14
step "気象"          uv run python scripts/fetch_weather.py --days 14
step "手動記録"       uv run python scripts/fetch_manual.py
step "気分記録"       uv run python scripts/emotion.py fetch --non-interactive
step "PHQ-9"         uv run python scripts/phq9.py fetch --non-interactive
step "排便記録"       uv run python scripts/bowel.py fetch --non-interactive
step "Toggl"         uv run python scripts/toggl.py fetch --days "$DAYS"
step "Toggl反映"      uv run python scripts/toggl.py push --days "$DAYS"
# 一括更新のキックは完了を待たない。取り込まれた明細は翌日の実行で回収される
step "MoneyForward"  uv run python scripts/mf.py fetch --refresh
# Habitica の日付をまたぐ処理（cron）を確定させる。Daily の未完了はこれでしか
# history に残らないので、走らせない日は「未達」でなく「欠測」になる
step "Habitica"     uv run python scripts/habitica.py cron

# 取得の後に置く。骨組みはその日の CSV を読んで書くので、取得が終わっていないと
# 前日までの値で埋まる。考察・Action Plan は従来どおり /journal が対話後に追記し、
# ここが書くのは skeleton マーカーの内側だけ
step "ジャーナル骨組み" uv run python scripts/journal_skeleton.py

echo ""
echo "Finished at $(date)"

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "=== 失敗した取得: ${FAILED[*]} ==="
  exit 1
fi

echo "=== Daily Routine Complete ==="
