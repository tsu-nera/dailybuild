# Habitica

行動の実行記録を持たせる先。dailybuild が「結果指標（不随意な観測）」を持つのに対し、
Habitica は「行動（随意の実行）」を持つ。**取得はまだ実装していない**（2026-08-29 時点で
API の性質を実測した段階）。認証情報は `config/habitica_creds.json`。

必須ヘッダは `x-api-user` / `x-api-key` / `x-client: <UserID>-<AppName>`。

- **rate limit は認証時 30 req/min（1リクエスト1消費）。未認証は1リクエスト
  5消費で実質 6 req/min。** `x-ratelimit-limit: 30` を額面で受けると5倍ハズす。
  ウィンドウは固定60秒。429 の `retry-after` は秒（小数）で必ず入る
- `https://habitica.com/export/*` は `/api/v3` 配下でなく `x-ratelimit-*` を
  返さない（制限の有無は未確認）
- API Usage Guidelines は「バックグラウンドの自動スクリプトはコール間30秒」と
  定めている。技術的上限より規約の方が厳しい。タスクごとにループで叩かない

## 達成率の分母

Daily の `history` は `{date, value, isDue, completed}` を持ち、**未完了日が
記録される**（org-mode の DONE と違って分母が取れる）。ただし1エントリ＝1 due日
ではなく **1エントリ＝1 cron実行**で、cron はユーザーがアクセスした日にしか
走らない。

**`completed / len(history)` を達成率としてはいけない。** 開いた日だけを母数に
した過大評価になる。実測（2026-08-29、アカウント2020-07-07 開設）で履歴に現れた
ユニーク日は 55日 / span 1295日 = **被覆率 4.2%**、361日・232日の空白があり、
その間の未達は一切残っていない。真の分母は due 日の暦であって history の長さでは
ない。機械が毎日 API を叩いて cron を確定させる前提で運用する（`dayStart: 5`、
`timezoneOffset: -540`）。

**Habit の `history` は `{date, value, scoredUp, scoredDown}` で `isDue` が無い。**
分母が原理的に取れないので、達成率を出すのは Daily だけ。Habit から取れるのは
回数のみ。

`/export/history.csv` は `Task Name, Task ID, Task Type, Date, Value` だけで
**`isDue` / `completed` を含まない**。分母目的では API の `history` を使う。

## 型の使い分け

判断基準は「毎日やるか」ではなく **「やらなかった日を数えたいか」**。

| 型 | 用途 | 罰 | 分母 |
|---|---|---|---|
| Daily | やると決めたこと | 未達で HP 減 | 取れる |
| Habit (up) | やれたらいいこと | 無し | 取れない |
| Habit (down) | 減らしたい行動 | 押したときだけ | 取れない |

**罰を受け入れるものだけが測定対象になる。** 罰を避けて Habit に落とすと、同時に
分母を捨てることになる。両立はできない。

悪習慣（down Habit）は押し忘れると過少に出るうえ、機械で裏を取る手段が無い
（YouTube 視聴時間は計測経路が無い）。改善サイクルの評価には載せない。

## difficulty（API では `priority`）

UI 表示は Difficulty、API のフィールド名は `priority`（Trivial 0.1 / Easy 1 /
Medium 1.5 / Hard 2）。`common/script/ops/scoreTask.js` では:

```
delta  = 0.9747 ** value
hpMod  = delta * conBonus * priority * 2          // 未達ダメージ
exp   += delta * intBonus * priority * crit * 6
gpMod  = delta * priority * crit * perBonus
```

**報酬と罰の両方に同じ係数で掛かり、分離できない。** このため達成率からの自動
調整ができない。達成率が低いことは「報酬を厚くすべき」とも「負荷が重すぎる」とも
読め、データでは区別がつかない。機械的に上げると、落ちている項目ほど罰が重くなり、
HP を行動の履行度として読む設計も壊れる（罰の倍率が変わると時系列が汚染される）。

**agent は difficulty を提案はするが変更しない。** 先に触るレバーは頻度と粒度で、
こちらは曜日別の達成率から客観的に判断できる。

`value`（色）も同じ `delta` 経由で報酬と罰の両方の倍率になる。赤いタスクは報酬も
罰も大きい。**削除して作り直すと `value` が 0 にリセットされる**（設定変更では
戻らない）。

## その他の落とし穴

- **`frequency` は Daily と Habit で意味が違う。** Daily では繰り返しの単位
  （`daily` = `everyX` 日ごと / `weekly` = `repeat` の曜日）、Habit では
  `counterUp` / `counterDown` のリセット周期。CSV に落とすときは列名を分ける
- **`weekly` + 全曜日 = 実質毎日。** `frequency` を見て「週次タスク」と分類すると
  誤る。週次タスクの `repeat` は分母を週1にするため**日曜のみ**にしてある
- `weekly` の `everyX` は「何週ごと」。**`everyX=0` にすると永久に due にならない**
  （`isDue` が常に False になり、黙って測定対象から外れる）
- **タスクを削除すると `history` も消える。** 個別削除でも Reset Account でも同じ。
  復元不可なので、削除前に `/export/userdata.json` を `data/habitica/backup/` へ
  退避する。**`userdata.json` には `apiToken` が平文で入るので redact してから
  保存する**
- `GET /user` の `needsCron` は `userFields` を指定すると返らない（指定なしの
  ときだけ計算される）
