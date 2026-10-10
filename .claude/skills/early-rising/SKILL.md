---
name: early-rising
description: 早起きの習慣化。寝坊した朝に前夜（帰宅・画面・入眠）と朝（起床・画面・出発・勉強カフェ到着）を区切りの lap に分けて直近の7日と並べ、センサーで分からない「なぜ」を1問だけ聞いて週ジャーナルに残す。「寝坊した」「起きられなかった」「夜ふかしした」「早起きできた」と言われたら使う。
user-invocable: true
allowed-tools: Bash, Read, Write, Edit
---

# 早起き（寝坊分析）

本人の申告で起動する。寝坊かどうかは本人が決める（同じ06:58でも寝坊の日とそうでない日がある）。
自動検出はしない。このスキルは手順だけを持ち、分析の中身は持たない。仮説は memory
`early-rising-hypotheses.md`、介入は `reports/journal/ACTIONS.md`、事例は週ジャーナルに置く。

## Step 1: 取得

```bash
ssh vaio 'bash -lc "~/repo/dailybuild/scripts/ops/daily-routine.sh --days 2"'
cd ~/repo/dailybuild-private && git stash -q; git pull --ff-only -q; git stash pop -q
```

取得は vaio だけが走らせる。「別の実行が進行中」で止まったら、vaio の `daily-routine.sh` が
終わるのを待ってから pull する。stash は、前回の Discussion が未コミットで残っていると pull が
止まるため（stash に何も無いときの pop の失敗は無視してよい）。

## Step 2: 事実を並べる（仮説はまだ読まない）

```bash
uv run scripts/early_rising.py laps --nights 7
uv run scripts/early_rising.py timeline    # 今朝に終わった夜
```

`laps` は「夜」と「朝」の2表を出す。夜は入眠までに、朝は起床から出発までに時間が溶けた
区間を見る。`-` はデータが無いことを示す（HA の state 履歴は 2026-10-01 夜以降、スマホの画面は
10-08 以降）。lap 表の列は、比べられるように毎回変えない。区切りの定義はスクリプトに置き、
ここで言い換えない。読むときの落とし穴:

- `last_used_app` はアプリを切り替えたときにしか届かない。画面が消えていてもアプリ名は残る
  ので、使用時間は画面 on の区間で読む
- 寝坊した夜だけでなく、寝坊しなかった夜と並べて違いを見る。寝坊した夜だけ見ても、
  何が効いているのかは分からない

## Step 3: 仮説と照合して1問

ここで初めて memory `early-rising-hypotheses.md` と `ACTIONS.md` の早起き関連の行を読み、
今夜の事実が仮説に合うか、外れるかを照合する。順番を逆にすると、仮説に合う事実だけを
拾ってしまう。

本人に出すのは、事実のタイムラインと前の夜との違いだけにする。原因は結論しない。
質問は**1問だけ**で、センサーで埋まらないこと（外出中の空白・その時のつもり）
に向ける。食事時刻は聞かない（本人の負担が大きく、2026-10 時点の事例では入眠を決めていたのは画面を止める時刻だった）。

## Step 4: 記録（回答の後）

- 週ジャーナル `reports/journal/YYYY-Wxx.md` に `**Discussion（寝坊分析）**: ` で1段落を書く。
  内容はその夜の lap 表の行、本人の回答、解釈。事例の数値は memory に書かない
  （引くときは `grep -n '寝坊分析' reports/journal/*.md`）
- 仮説ファイルを書き換える。外れた仮説は消し、追記を重ねて積まない（履歴はジャーナルにある）
- 介入を始めた・やめたときは `ACTIONS.md` に1行。夜の介入の実装は saru9000 の担当
- private リポジトリを commit・push する
