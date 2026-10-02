---
name: daily-review
description: データ取得→レポート生成→AIレビューを一括実行する日次レビュースキル
user-invocable: true
allowed-tools: Bash, Read, Glob
---

# 日次レビュースキル

データ取得、レポート生成、AIレビューを3ステップで実行する。
レビュー後のディスカッションを経て、記録は `/journal` スキルで保存する。

## オプション

| オプション | 説明 | デフォルト |
|------------|------|------------|
| `--no-fetch` | Step 1 の ssh 起動をスキップ（rsync・pull・`--state-only` は行う） | なし |
| `--fetch N` | 取得日数を指定（例: `--fetch 7` で過去7日分） | 2 |
| `--only body\|sleep\|mind` | 指定したレポートのみ生成・レビュー | 全3種 |

例:
- `/daily-review` → 全3ステップ実行
- `/daily-review --no-fetch` → vaio の起動はスキップ（pull と STATE 再生成は行う）、レポート生成→レビュー
- `/daily-review --fetch 7` → 過去7日分取得してから全レポート生成
- `/daily-review --only body` → 体組成レポートのみ生成・レビュー
- `/daily-review --no-fetch --only sleep` → 睡眠レポートのみ生成・レビュー

## Step 0: 起動時刻の確認

最初に現在の日時と曜日を確認する。

```bash
date '+%Y-%m-%d %H:%M %A'
```

この値を `CURRENT_DATE` / `CURRENT_TIME` / `CURRENT_WEEKDAY` として保持し、Step 3 のレビューで必ず参照する。
特に **当日（CURRENT_DATE）のデータは未完了**である点に注意する（後述「当日データの扱い」）。

続けて次の2つを読む。レポートは常に「今の状態」しか持たないので、これを読まないと
**毎回ゼロから同じトレンドを導出し直し、前回なんと言ったかを知らないまま
レビューすることになる**。同じ助言を繰り返す失敗と、何日も続く異常を
「今日始まったこと」として書く失敗が、どちらもここで防げる。

```bash
cat reports/journal/STATE.md      # 現在値・ストリーク・未解決アクション・鮮度
cat reports/journal/JOURNAL.md    # 索引。1週1行
```

STATE.md は生成物で git の追跡対象外。**新しい環境では存在しない**ので、
無ければ `uv run scripts/journal_skeleton.py --state-only` で作ってから読む。

`STATE.md` は生成物で、**継続日数と未解決アクションの一次情報はここ**。
文中で数え直さない。索引の最新週が今週でない場合、その空白期間はレビューが
回っていない期間なので、Step 3 でその旨に触れる。

## Step 1: データ取得

取得は vaio だけが走らせる。**`--no-fetch` の場合は ssh 起動（1つ目）だけ省き、
rsync・pull・`--state-only` は行う**（vaio の 12:00 の取得結果を受け取るため）。

`--fetch N` が指定されている場合はNを使用する。指定がなければ `2` を使用する。

```bash
ssh vaio 'bash -lc "~/repo/dailybuild/scripts/ops/daily-routine.sh --days <N>"'
rsync -a vaio:~/repo/dailybuild/logs/daily-routine/ logs/daily-routine/
git -C ~/repo/dailybuild-private pull --rebase --autostash
uv run scripts/journal_skeleton.py --state-only   # STATE.md / metrics_daily.csv は追跡外なので mouse で作り直す
```

STATE.md の「最終実行」「ログの警告」は手元の `logs/` を読む。ログは vaio にしか
書かれずリポジトリにも入らないので、rsync を省くと mouse に残った古いログが表示される。

**ssh が失敗したとき（vaio 停止・tailnet 断）は、ローカルで `daily-routine.sh` / `daily-fetch.sh` を代わりに
走らせない。** 取得元が2台になると同じ CSV を両側で書き換える。失敗を報告し、
pull と `--state-only` だけ行って手元の既存データでレビューする（rsync も失敗するので、「最終実行」は古い日付のまま出る）。

ssh の出力（routine のログ）をそのまま読む。個々の取得コマンドは `daily-fetch.sh` が持ち、
1ステップ失敗しても後続は続行して、失敗したステップ名が最後にまとめて出る。

**報告してよい失敗・警告は、Step 3 で読む入力（レポート3種・日次記録・気分記録）を
欠けさせるものだけ**。それ以外は、スクリプトやパイプライン表に出ていても末尾を含めて触れない。
扱う場合は、どのデータが欠けた状態でレビューしているかを明示する。

## Step 2: レポート生成

`--only <type>` が指定されている場合は該当するコマンドのみ実行する。指定がなければ3つすべて実行する。

```bash
# 体組成レポート（直近7日）-- --only body または指定なしの場合
uv run python scripts/generate_body_report_daily.py --days 7 --no-charts

# 睡眠レポート（直近30日）-- --only sleep または指定なしの場合
uv run python scripts/generate_sleep_report_daily.py --days 30 --no-charts

# メンタルレポート（直近14日）-- --only mind または指定なしの場合
uv run python scripts/generate_mind_report_daily.py --days 14 --no-charts
```

`--no-charts` は Step 3 のレビューが画像を読まないため。人が `mdcat` で見るときは
外して叩くとグラフ付きで出る。

エラーがあれば報告する。

## Step 3: AIレビュー

`--only <type>` が指定されている場合は該当するレポートのみ読み込む。指定がなければすべて読み込む。

- `tmp/body_report/REPORT.md`（body または指定なし）
- `tmp/sleep_report/REPORT.md`（sleep または指定なし）
- `tmp/mind_report/REPORT.md`（mind または指定なし）

加えて、日次記録（気分・身体・頭・睡眠の主観スコアとコメント）の直近7日分を
読み込む（`--no-fetch` の場合も含む）:

```bash
uv run scripts/daily.py morning show --days 7
uv run scripts/emotion.py show --days 7
```

STATE.md の「直近7日 / 前7日 / 変化」列は機械が同じ式で毎日出すので、レポートの
日次テーブルを目視で追うより判断がぶれない。**トレンドの一次情報はこちらを使い、
レポートの日次テーブルは裏取りに使う。**

当週の週ファイル（`reports/journal/$(date '+%G-W%V').md`）は、**前回の判断の
理由を辿る必要があるときだけ**開く。数値・ストリーク・アクションの状態は
STATE.md に入っているので、通常は開かなくてよい。

過去の週を辿る必要があるときだけ、索引から該当する `reports/journal/YYYY-Wxx.md` を開く。

さらに、週次目標の宣言値を読み込む（`config/targets.yaml` の `review: weekly`）:

```bash
uv run python scripts/show_targets.py --interval weekly
```

このスクリプトは目標値・方向（up/down/zero）の一覧を返すだけで、現在値や残差は算出しない。
**現在値はレポートから読み取って自分で評価すること**（Zone2の残り分、睡眠負債の現在値など）。

### 当日データの扱い

`CURRENT_DATE` の活動量（歩数・Zone2・サイクリング・カロリー・栄養）は進行中の未完了データ。低くても「休養」と評価せず、トレンド・週次目標は前日までの確定データで判定する。睡眠・HRV・RHR は起床時点で確定するため当日値を通常評価してよい。

### レビュー観点

#### 継続性（State / Journal）
- STATE.md の「変化」列で、直近7日が前7日から動いた指標を拾う。ここが一次情報
- 継続しているかどうかは STATE.md のストリーク表を見る。**自分で数え直さない**。
  表に無い（2日未満）なら「今日始まった」
- **本文に「N日連続」の日数を書かない。**「継続中」「今日始まった」だけ書き、
  日数が要るなら STATE.md を見る。日数はデータの訂正で後から変わる（実際
  2026-09-05 に歩数の訂正で 5日連続 → 3日連続 に動いた）。週ファイルは不変なので、
  書いた瞬間に嘘になりうる記述をそこに残さない
- STATE.md の未解決アクションに触れる。触れずに新しい助言だけ足さない。
  `撤回` 済みの助言を再発行しない（ACTIONS.md に理由がある）
- STATE.md のパイプライン表で `要確認` のものは、Step 1 の範囲に入るものだけ扱う
- 索引に空白期間がある場合、その間はレビューが回っていない。データはあるので
  「記録が無い」と「起きていない」を混同しない

#### フィットネス（Body）
- 体組成: 体重・筋肉量・体脂肪率のトレンド、FFMI の進捗（目標値は `show_targets.py` の出力を見る。スキル本文に数値を書かない）
- 体重トレンド（kg/週。カロリー収支には換算しない）とタンパク質摂取量（g/kg/日、1.6-1.8が下限、2.0は上限で必達ラインではない）。タンパク源の記録が途切れたときだけ記録を促す。記録日数を分母にした達成率は出さない
- 筋トレ: 実施頻度・時間・強度（HR）の傾向
- 部位別セット数の週内残量（body レポートの「今週の部位別セット数」）。残りの日数への配置を決めるのに使う。0セットの部位があれば次にそこを入れる。export 未反映の警告が出ている週は残量が過少なので断定しない
- サイクリング: 距離・時間・強度の傾向、Z2/Z3-4/Z5 ゾーン分布
- 異常値や急激な変動の検出

#### 睡眠（Sleep）
- 睡眠時間の傾向（7-8時間が理想）
- 睡眠効率（85%以上が目標）
- 深い睡眠・REM睡眠の割合
- 就寝・起床時刻の規則性
- 睡眠負債: sleep レポートのアルゴリズム値を参照（欠測日を睡眠0hで計上するため、連続欠測週は絶対値を使わない）
- 曜日による傾向の違い

#### メンタル（Mind）
- HRVトレンド（上昇=回復良好、下降=疲労蓄積）
- 安静時心拍数の変動
- 呼吸数・SpO2の異常検出
- 運動負荷と回復のバランス

#### 週次目標進捗（Targets）
- `config/targets.yaml` で宣言された週次目標について、目標値とdirectionを確認
- 現在値はBody/Sleep/Mindレポートから読み取り、残差・達成状況を自分で判断
- 例: Zone2が週150min目標に対してbody/workoutレポートのfatBurn週合計と比較してあと何分か、睡眠負債がsleepレポートの現在値で目標0hからどれだけ離れているか
- 未達の目標があれば「今日のアドバイス」に残り日数で達成可能なアクションを盛り込む

#### 日次記録（Daily Summary）
対象は `daily.py morning show` が出す気分・身体・頭・睡眠の4指標（1-5、高=良好）とコメント。すべて高=良好の向きに揃えてあるので、指標ごとの解釈方針を別途参照する必要はない。
- 各指標のトレンドを確認する。`head_score`（頭の軽さ）は移行分が全欠測なので、直近の実測値が出てくるまでは他の3指標より短い期間しか評価できない
- 主観スコアと客観指標（HRV・睡眠等）の一致・乖離を指摘する（例: HRV低下なのに主観スコアが高い）
- **原則**: HRV/RHRは自律神経回復のみを測る計器。末梢・構造疲労、エネルギー利用能、睡眠*時間*不足は原理的に映らない。乖離時はまず各指標が測る構成概念を切り分け、身体疲労は主観を主計器とする
- コメント欄の自覚症状・特記事項を数値と突き合わせる

#### 気分記録（Emotion）
`emotion.py show` の出力。日次記録（1日1点・回答日基準）と違い日内に複数点ある。
- **主指標は陽性感情の頻度と最終出現**。陰性の量ではない（`config/emotion_def.yaml` が語彙を陽性7・陰性4に寄せているのはこのため）。「陽性がN日途切れている」は書く価値がある
- **日内の変化は事実だけ返す**。抑うつ状態では1日の中の改善が記憶に残らないので、差を出すこと自体が目的。「改善しています」等の解釈・助言を付けない
- **記録の無い日を不調と読まない**。断続的な記録で運用は成立している。被覆率を上げる助言をしない
- 語の出現回数は n 不足のため当面は参考値。1〜2件の差から傾向を語らない

### 出力形式

以下の形式で日本語で報告する。

```
## 日次ヘルスレビュー（YYYY-MM-DD）

### 総合コンディション
全体的な状態を一言で（例: 良好 / 注意 / 要改善）

### 前回からの変化
骨組みの「変化」列で動いた指標と、前回エントリからの継続/新規を1-3行。
前回が数日前なら、その間隔も書く

### Body（体組成）
- 現状サマリー
- 良い点 / 注意点

### Sleep（睡眠）
- 現状サマリー
- 良い点 / 注意点

### Mind（メンタル・回復）
- 現状サマリー
- 良い点 / 注意点

### 主観 vs 客観
日次記録の主観スコアと客観指標（HRV・睡眠等）の一致・乖離を指摘

### 今日のアドバイス
具体的なアクション（2-3個）
```

## Step 4: ジャーナルへ記録（確認不要）

`journal` スキルの daily モードで、当日エントリの `review:` 区間・`ACTIONS.md`・索引を更新する。**「記録しますか?」と聞かず、レビューを出したらそのまま書く。**（当週の Weekly Summary は週が完了するまで書かない）

その後の会話で深掘りした内容は Discussion に追記する（区間外なので上書きされない）。

書き終えたら `dailybuild-private` の変更を commit・push する。週ファイルは vaio が
skeleton 区間、mouse が区間外を書くので、mouse が push しないと次の pull で衝突する。

```bash
git -C ~/repo/dailybuild-private add -A && git -C ~/repo/dailybuild-private commit -m "chore(journal): daily review YYYY-MM-DD" && git -C ~/repo/dailybuild-private push
```

push が拒否されたら `git -C ~/repo/dailybuild-private pull --rebase` してから再度 push する。
