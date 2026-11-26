"""習慣（Toggl Focus のクライアント「良い習慣」「悪い習慣」のプロジェクト）

- daily: focus_entries.csv と focus_projects.csv から reports/habits_daily.csv を作る
- weekly: habits_daily.csv を週ごとに数え、設定とのずれを検出する（数え方はここに1本）
- config: 設定（yaml）と habits_daily.csv の読み込み

設計は docs/habits.md。
"""
