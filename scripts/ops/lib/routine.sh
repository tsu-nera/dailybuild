# shellcheck shell=bash
# 日次・週次の routine が共有する関数ライブラリ。source しても何も実行しない。
#
# 入口（*-routine.sh）は routine_entry を、中身（*-fetch.sh）は routine_fetch_init → step → routine_fetch_finish を使う。
# 入口と中身を分けているのは、取得の失敗と git の失敗を別々に扱うため（取得が失敗しても取れたぶんは commit・push する）。

# 入口: flock → private を pull → 中身 → commit → pull --rebase → push。終了コードは中身のものを返す。
# 中身が途中で失敗しても取れたソースのデータは正しいので、commit・push は行う。rebase が衝突したら
# abort して非ゼロで止まる（強制 push はしない）。同じ衝突は次回も起きるので、解消は人が行う。
# それまでの取得はローカルに commit され続け、窓の短いソースも欠測にならない。
#
# Usage: routine_entry <label> <中身のスクリプト> [中身への引数...]   # 戻らずに exit する
routine_entry() {
  local label="$1" fetch="$2"; shift 2
  local private="${DAILYBUILD_PRIVATE:-$HOME/repo/dailybuild-private}"

  # 日次と週次・timer と ssh 起動が重なったら、後から来た方を断る（同じ private を書くので lock は1つ）
  exec 9>"$private/.git/dailybuild-routine.lock" || exit 1
  if ! flock -n 9; then
    echo "別の実行が進行中のため中止する" >&2
    exit 75
  fi

  # pull に失敗しても取得は止めない。git の問題で取得を止めると、Toggl のように
  # 窓の短いソースが欠測になる。rebase 途中の状態だけは残さない
  if ! git -C "$private" pull --rebase; then
    git -C "$private" rebase --abort 2>/dev/null
    echo "警告: private の pull --rebase に失敗。取得は続け、ローカルに commit する" >&2
  fi

  ROUTINE_OUT="$(mktemp)"
  trap 'rm -f "$ROUTINE_OUT"' EXIT
  "$fetch" "$@" 2>&1 | tee "$ROUTINE_OUT"
  local rc=${PIPESTATUS[0]}

  git -C "$private" add -A
  if ! git -C "$private" diff --cached --quiet; then
    local msg failed
    msg="data: $label routine $(date '+%Y-%m-%d %H:%M')"
    failed="$(sed -n 's/^=== 失敗した取得: \(.*\) ===$/\1/p' "$ROUTINE_OUT" | tail -n 1)"
    [ -n "$failed" ] && msg="$msg (failed: $failed)"
    if ! git -C "$private" commit -q -m "$msg"; then
      echo "エラー: private の commit に失敗" >&2
      exit 1
    fi
  fi

  # 差分が無くても、前回の衝突で push できなかった commit が残りうるので毎回 push する
  if ! git -C "$private" pull --rebase; then
    git -C "$private" rebase --abort 2>/dev/null
    echo "エラー: rebase が衝突したため中断した。ローカル commit は残してある（強制 push はしない）" >&2
    exit 1
  fi
  if ! git -C "$private" push; then
    echo "エラー: private の push に失敗" >&2
    exit 1
  fi

  exit "$rc"
}

# 中身の前処理: リポジトリ直下へ cd し、private のマウントを検査し、以後の出力を
# logs/<label>-routine/YYYY-MM-DD.log へも書く。
#
# Usage: routine_fetch_init <label>
routine_fetch_init() {
  local label="$1"
  cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 1

  # data/ reports/ は dailybuild-private への symlink。未設定のまま走らせると
  # 各スクリプトが public 側にディレクトリを作り、既存データを見失う。
  local d
  for d in data reports config/private; do
    if [ ! -L "$d" ] || [ ! -d "$d" ]; then
      echo "エラー: $d が dailybuild-private にマウントされていません" >&2
      echo "  ./scripts/setup_private_links.sh を実行してください" >&2
      exit 1
    fi
  done

  local log_dir="logs/$label-routine"
  mkdir -p "$log_dir"
  exec > >(tee -a "$log_dir/$(date +%Y-%m-%d).log") 2>&1

  FAILED=()
}

# 失敗しても後続を続ける。ステップ名を控えて最後に報告する。所要秒数も出す（遅いステップを見つけるため）。
# 成否を終了コードで返すので、後続を条件付きにしたいときは if step ...; then で受ける。
#
# Usage: step <表示名> <コマンド> [引数...]
step() {
  local name="$1"; shift
  local start=$SECONDS
  echo ""
  echo ">>> $name"
  if "$@"; then
    echo "<<< $name ($((SECONDS - start))s)"
    return 0
  fi
  echo "!!! $name に失敗 ($((SECONDS - start))s)（後続は続行する）"
  FAILED+=("$name")
  return 1
}

# 中身の後処理: 失敗したステップをまとめて出し、あれば非ゼロで終わる。
# 「=== 失敗した取得: ... ===」の行は routine_entry が commit message に写すので書式を変えない。
#
# Usage: routine_fetch_finish <表題>   # 戻らずに exit する
routine_fetch_finish() {
  local title="$1"
  echo ""
  echo "Finished at $(date)"

  if [ ${#FAILED[@]} -gt 0 ]; then
    echo "=== 失敗した取得: ${FAILED[*]} ==="
    exit 1
  fi

  echo "=== $title Complete ==="
  exit 0
}
