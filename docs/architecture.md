# コード構成とテンプレート

## ディレクトリ構成

- `scripts/` - 実行スクリプト
- `src/lib/` - APIクライアントライブラリ
  - `healthplanet_official.py` - HealthPlanet公式OAuth API（体重・体脂肪率のみ）
  - `healthplanet_unofficial.py` - HealthPlanet非公式API（全項目取得可）
  - `toggl/` - Toggl Track（`client.py` API クライアント、`store.py` CSV 読み書き、`render.py` markdown 出力）
  - `mf/` - MoneyForward ME（`client.py` Playwright セッション、`store.py` CSV 読み書き、`render.py` markdown 出力）
  - `food/` - 食事記録（`mext.py` 日本食品標準成分表のパーサ）
  - `templates/` - Jinja2テンプレートとレンダラー
    - `renderer.py` - レポートテンプレートレンダラー
    - `filters.py` - カスタムJinja2フィルタ
  - `analytics/` - データ分析ライブラリ
    - `body.py` - 体組成分析
    - `sleep.py` - 睡眠分析
    - `mind.py` - メンタルコンディション分析
  - `utils/` - 共通ユーティリティ
    - `report_args.py` - レポート引数パースと期間フィルタリング
- `templates/` - Markdownレポートテンプレート
  - `body/` - 体組成レポート
    - `base.md.j2` - 基本構造
    - `daily_report.md.j2` - 日次レポート
    - `interval_report.md.j2` - 週次隔レポート
    - `sections/` - セクションテンプレート
  - `mind/` - メンタルコンディションレポート
    - `base.md.j2`, `daily_report.md.j2`
    - `sections/` - HRV、心拍、睡眠、生理指標のセクション
  - `sleep/` - 睡眠分析レポート
    - `base.md.j2`, `daily_report.md.j2`, `interval_report.md.j2`
    - `sections/` - サマリー、効率、ステージ、タイミング、サイクル、週次データのセクション
- `config/` - API認証情報（gitignore対象）
- `data/` - 出力CSV（`dailybuild-private` への symlink）
- `notes/` - Jupyter notebooks（実験・分析用）
- `reports/` - 生成されたレポート（`dailybuild-private` への symlink）

## テンプレートアーキテクチャ

全レポートは統一されたパターンを採用:

1. **データ準備**: `prepare_*_report_data()` 関数がコンテキスト辞書を構築
2. **テンプレートレンダリング**: レンダラークラス（`BodyReportRenderer`, `MindReportRenderer`, `SleepReportRenderer`）がJinja2テンプレートを適用
3. **テンプレート構成**:
   - `base.md.j2` - セクションブロック定義
   - `*_report.md.j2` - base継承、セクションinclude
   - `sections/*.md.j2` - 再利用可能なセクション（条件付きレンダリング対応）

## カスタムフィルタ

`src/lib/templates/filters.py` で定義された共通フィルタ:

- `format_change(value, unit, positive_is_good)` - 変化量フォーマット（良い変化を太字化）
- `date_format(date)` - 日付フォーマット
- `number_format(value, decimals)` - 数値フォーマット

## 期間フィルタリング

`src/lib/utils/report_args.py:filter_dataframe_by_period()` で統一されたデータフィルタリング:

```python
df_filtered = filter_dataframe_by_period(
    df=dataframe,
    date_column='date',  # または 'dateOfSleep'
    week=week, month=month, year=year, days=days,
    is_index=True  # 日付がindexの場合
)
```
