---
name: weekly-review
description: 週次レポート生成→AIレビューを実行する週次レビュースキル（GTD準拠・日曜実施）
user-invocable: true
allowed-tools: Bash, Read, Glob
---

# 週次レビュースキル

GTDのWeekly Reviewに合わせて日曜に実施する。今週分のデータを集約し、曜日傾向・規則性・先週比を評価する。
レビュー後のディスカッションを経て、記録は `/journal` スキルで保存する。

## オプション

| オプション | 説明 | デフォルト |
|------------|------|------------|
| `--week N` | 対象ISO週を明示指定（例: `--week 17`） | current |
| `--year YYYY` | 年を明示指定 | 今年 |
| `--only body\|sleep\|mind` | 指定したレポートのみ生成・レビュー | 全3種 |

例:
- `/weekly-review` → 今週の全3種をレビュー
- `/weekly-review --week 17` → ISO週17をレビュー
- `/weekly-review --only mind` → メンタルのみ

## Step 1: レポート生成

`--only <type>` 指定時は該当のみ実行。`--week` `--year` 指定時はそのまま渡す。

```bash
cd /home/tsu-nera/repo/dailybuild

# 体組成
uv run python scripts/generate_body_report_daily.py --week current

# 睡眠
uv run python scripts/generate_sleep_report_daily.py --week current

# メンタル
uv run python scripts/generate_mind_report_daily.py --week current
```

出力先: `reports/{body,sleep,mind}/weekly/YYYY-Wxx/REPORT.md`

エラーがあれば報告する。

## Step 2: 今週のjournalを読み込み

その週の `reports/journal/YYYY-Wxx.md` を読む（`date '+%G-W%V'`、`--week` 指定時はその週）。日次エントリは `## YYYY-MM-DD (曜)` として同一ファイル内にある。

前週の調整が効いたかを見るため、前週ファイルの Next Week's Adjustments も読む。

Step 3 のレビューで「定性的な文脈」として参照する：
- 各日の Discussion・Action Plan
- Action Plan の達成状況（Evening Check-in があれば）
- 週内の気づきの推移

## Step 2.5: 中長期目標の読み込み

`config/targets.yaml` から weekly より長い粒度（monthly / quarterly）の目標を読み込む。
週次レビューは中長期目標への進捗確認に向くため、weekly目標は対象外（daily-reviewで毎日見ているため）。

```bash
uv run python scripts/show_targets.py --interval monthly quarterly
```

このスクリプトは目標値・directionを返すだけ。現在値はBody/Sleep/Mindレポートから読み取って評価する。

## Step 2.7: PHQ-9

うつの重症度（0〜27点）を週1回測る。**主観の唯一の検証済み計器**で、`mind_score`
（1〜5・自作）が下限に張り付いて日次では情報を運べない期間でも、項目ごとに割れて
変化を拾う。定義と運用の詳細は CLAUDE.md の「PHQ-9（週次）」節。

```bash
uv run scripts/phq9.py fetch
tail -5 data/phq9.csv
```

**今週まだ回答が無ければ、回答用URLを出して促す**（レビューはその週の分が
無いまま進めてよい。促すのは1回で、催促を繰り返さない）:

```bash
uv run scripts/phq9.py url
```

読み方:

- **週ごとの差を「変化」と読まない。** 想起期間が2週間なので連続する2点は1週分を
  共有する。2週窓の移動平均として傾きを見る
- **MCID（意味のある変化）= 5点。当ててよいのは窓が重ならない比較だけ**
  （ベースライン vs 4週後 / 8週後）。隣接する週の差に当てない
- 重症度の帯: 0-4 ほぼなし / 5-9 軽度 / 10-14 中等度 / 15-19 中等度〜重度 / 20-27 重度
- **合計だけでなく項目の内訳を見る。** 合計が動かなくても項目の分布は動く。
  どの症状が動いてどれが動かないかが、施策の当たり外れの手がかりになる
- 9項目目（死・自傷）は合計に3点まで乗せる。帯の判断は合計で行い、この項目単独を
  取り上げて安全確認に入らない（[本人の方針] 強い言葉で記録が止まるほうが損失が大きい）
- `total` が NaN の回は未回答が混じっている。合計として扱わない

## Step 3: AIレビュー

生成された3つのREPORT.md（量的データ） + Step 2 のdaily journal（定性的データ）を統合してレビューする。

### レビュー観点（週次特化）

#### 体組成（Body）
- 週内の体重・筋肉量・体脂肪率の推移（増減トレンド）
- 週合計のカロリー収支とタンパク質摂取
- 平日/週末の食事パターンの違い
- 月間目標（+0.75kg/月）に対する週次進捗

#### 睡眠（Sleep）
- **就寝・起床時刻の規則性**（週次レビューで最重要）
- 平日/週末の睡眠負債とリカバリーパターン
- 週合計の睡眠時間・効率の傾向
- 中途覚醒の頻度傾向

#### メンタル（Mind）
- HRV/RHRの週内推移と曜日傾向
- 自律神経の緊張⇄回復サイクル
- 活動量と回復のバランス（過活動/過少活動の検出）
- 週内の不安定要因の特定

#### PHQ-9
- 今週の点数、前週差、ベースライン（初回）からの差
- 項目ごとの内訳の変化（どの症状が動いたか）
- 重症度の帯が変わったか
- **判定日（ベースラインから8週後）が近ければ、MCID 5点に対する残差を出す**

#### 中長期目標（Targets）
- Step 2.5 で読み込んだ monthly / quarterly 目標について、今週時点の現在値をレポートから読み取り進捗を評価
- 例: FFMI 21.0（monthly）に対して今週末の値はいくらで、目標までの残差・直近の伸びはどうか
- 進捗が芳しくない目標は「来週への調整ポイント」に具体アクションとして反映

### 出力形式

```
## 週次ヘルスレビュー（YYYY-Wxx: MM/DD - MM/DD）

### 今週の総合コンディション
全体評価を一言で（例: 安定 / 軽度乱れ / 要調整）

### Body（体組成）
- 週内推移サマリー
- 良い点 / 注意点

### Sleep（睡眠）
- 規則性の評価
- 良い点 / 注意点

### Mind（メンタル・回復）
- 自律神経バランスの評価
- 良い点 / 注意点

### Action Plan の達成度
今週のdaily journalで宣言したAction Planの達成状況をレビュー
- 達成できたもの / できなかったもの
- 未達の要因分析

### 今週の振り返り
- 特に良かった日/悪かった日とその要因
- 曜日パターンや繰り返しの傾向
- daily journalで繰り返し現れたテーマ

### PHQ-9
- 今週の点数 / 前週差 / ベースライン差 / 重症度の帯
- 動いた項目・動かない項目
- 未回答の週はその旨だけ書く

### 中長期目標の進捗
- monthly/quarterly 目標ごとに「目標値 / 現在値 / 残差 / 直近トレンド」
- 達成軌道に乗っているか、要調整か

### 来週への調整ポイント
具体的なアクション（2-3個）。今週のLessons Learnedと中長期目標の残差を踏まえる。
```

レビュー後、ディスカッションを経て記録を残す場合は `/journal` を使用する。
