#!/bin/bash
# 日次のデータ取得（ソースごとの取得リスト＋ジャーナル骨組み）。判断は一切せず、副作用だけを起こす。
# 直接は呼ばず、入口の daily-routine.sh（flock → pull → 本スクリプト → commit・push）経由で回す。
# 取得は vaio だけが走らせる。mouse では実行しない。
#
# 途中で失敗しても後続を止めない（Google Health が落ちても体組成・家計簿は取りに行く）。
# ただし黙って成功扱いにはせず、失敗したステップ名を最後にまとめて出し、
# 非ゼロで終了する。cron から回す場合もログに残る。
#
# Usage:
#   scripts/ops/daily-fetch.sh              # 直近2日
#   scripts/ops/daily-fetch.sh --days 7
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

DAYS=2
DAYS_EXPLICIT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --days) DAYS="$2"; DAYS_EXPLICIT=1; shift 2 ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done

# data/ reports/ は dailybuild-private への symlink。未設定のまま走らせると
# 各スクリプトが public 側にディレクトリを作り、既存データを見失う。
for d in data reports config/private; do
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

# 一律 --days 2 が根本原因だった（Issue #70/#125）: 実行が失敗した日は
# 窓の外に落ち、二度と再取得されない。--days をこの起動時に明示された
# ときだけ転送し、そうでなければ渡さずエンドポイントごとの既定窓
# （lib.googlehealth_fetcher.ENDPOINTS の default_days）に委ねる。
# Toggl は 30 req/h のクォータと push の一致件数コストがあるため対象外
# （常に "$DAYS" を明示で渡す・既定2のまま）。
if [ "$DAYS_EXPLICIT" -eq 1 ]; then
  step "Google Health" uv run python scripts/fetch_googlehealth.py --days "$DAYS" --non-interactive
else
  step "Google Health" uv run python scripts/fetch_googlehealth.py --non-interactive
fi
step "HealthPlanet"  uv run python scripts/fetch_healthplanet.py
# Hevy の export 取得。セッションの有無は Health Connect 経由で exercise.csv に
# 入るが、部位別セット数の内訳は export にしか無い（Hevy に API は無い）
step "Hevy"          uv run python scripts/hevy.py fetch
# Timeline の export 取得。月1回ほどの手動 export なので、Drive 側が前回と同じなら
# 何もせず終わる（場所ごとの訪問は export にしか無い）
step "Timeline"      uv run python scripts/timeline.py fetch
# 訪問日数の多い未解決の place ID の名前を Places API で引く（キーが無ければ warning だけで 0）
step "Timeline names" uv run python scripts/timeline.py names
step "日出・日入"     uv run python scripts/fetch_sun_times.py --days 14
step "気象"          uv run python scripts/fetch_weather.py --days 14
step "Home Assistant" uv run python scripts/fetch_homeassistant.py
# Google Forms は config/forms.yaml（レジストリ）から列挙し、1フォーム1ステップで回す。
# deprecated も fetch は続ける。レジストリが読めなければそれを1つの失敗として出して続行する
if FORM_LIST=$(uv run python scripts/forms.py fetch-list); then
  # here-string のまま回すと fetch が stdin を食うので、先に配列へ移す
  mapfile -t FORM_LINES <<< "$FORM_LIST"
  for line in "${FORM_LINES[@]}"; do
    [ -n "$line" ] || continue
    step "${line#*$'\t'}" uv run python scripts/forms.py fetch "${line%%$'\t'*}"
  done
else
  echo "!!! フォームのレジストリ の読み込みに失敗（後続は続行する）"
  FAILED+=("フォームのレジストリ")
fi
step "Toggl"         uv run python scripts/toggl.py fetch --days "$DAYS"
step "Toggl 2.0"     uv run python scripts/toggl.py fetch-focus --days "$DAYS"
step "Toggl反映"      uv run python scripts/toggl.py push --days "$DAYS"
step "Todoist"       uv run python scripts/todoist.py fetch --update
# 一括更新のキックは完了を待たない。取り込まれた明細は翌日の実行で回収される
step "MoneyForward"  uv run python scripts/mf.py fetch --refresh
# Habitica の日付をまたぐ処理（cron）を確定させる。Daily の未完了はこれでしか
# history に残らないので、走らせない日は「未達」でなく「欠測」になる
step "Habitica"     uv run python scripts/habitica.py cron
# Google Calendar（primary）の読み取り専用の写し。骨組みと events.jsonl が予定を読むので、それらより前
step "Google Calendar" uv run python scripts/gcalendar.py fetch --days "$DAYS"

# 取得の後に置く。骨組みはその日の CSV を読んで書くので、取得が終わっていないと
# 前日までの値で埋まる。考察・Action Plan は従来どおり /journal が対話後に追記し、
# ここが書くのは skeleton マーカーの内側だけ
step "ジャーナル骨組み" uv run python scripts/journal_skeleton.py
# 行動イベントの正規化ストリーム（reports/events.jsonl）。取得の後でないと当日分が欠ける。
# 期待するソースが 0 件なら失敗扱いになり、ここで fetch の沈黙故障が表に出る
step "行動イベント"   uv run python scripts/events.py build
# 観察日記（reports/observation/）。events.jsonl を読むのでその後。遅れて届く同期を拾うため3日ぶん書き直す
step "観察日記"       uv run python scripts/observation.py build --days 3

echo ""
echo "Finished at $(date)"

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "=== 失敗した取得: ${FAILED[*]} ==="
  exit 1
fi

echo "=== Daily Routine Complete ==="
