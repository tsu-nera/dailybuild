#!/usr/bin/env bash
# 今週の週次ヘルスレビューIssueを作成する
# 使用例: ./scripts/create_weekly_issue.sh

set -euo pipefail

cd "$(dirname "$0")/.."

# 今週の月曜〜日曜を計算
MONDAY=$(date -d "last monday" +%Y-%m-%d 2>/dev/null || date -v-last-monday +%Y-%m-%d)
SUNDAY=$(date -d "last monday + 6 days" +%Y-%m-%d 2>/dev/null || date -v+6d -v-last-monday +%Y-%m-%d)
WEEK_NUM=$(date +%V)
YEAR=$(date +%Y)

TITLE="週次ヘルスレビュー W${WEEK_NUM} (${MONDAY} ~ ${SUNDAY})"

# 既存のOpenIssueが存在するか確認
EXISTING=$(gh issue list --label "weekly-review" --state open --json number,title --jq '.[0].number' 2>/dev/null)
if [ -n "$EXISTING" ]; then
  echo "既にOpenな週次レビューIssueが存在します: #${EXISTING}"
  echo "新規作成をスキップします。"
  exit 0
fi

BODY=$(cat <<EOF
# 週次ヘルスレビュー ${YEAR} W${WEEK_NUM}

**期間**: ${MONDAY} 〜 ${SUNDAY}

## 日次レビューログ

このIssueには毎日の \`/daily-review\` 結果がコメントとして追記されます。

## 週次サマリー

（週末にまとめ）
EOF
)

ISSUE_URL=$(gh issue create \
  --title "$TITLE" \
  --body "$BODY" \
  --label "weekly-review")

echo "Issue作成完了: $ISSUE_URL"
