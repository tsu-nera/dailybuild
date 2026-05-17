## 背景・動機

「Zone2トレーニング（低強度・脂質酸化優位の有酸素ベース）が有効」という情報を受け、その時間を正確に追跡したい。Fitbit AZM（fat_burn/cardio/peak）が不正確と考え PR #19 で %HRR カルボーネン Z1-Z5 を実装したが、`issues/013_zone/report.md` での3ヶ月検証の結果、**新アルゴリズムの "Z2" もいわゆる生理学的 Zone2 ではない**ことが判明した。

### 検証で確定した事実（詳細: `issues/013_zone/report.md`）

- データ・実装・%HRR手法そのものは健全。バグではない
- Tanaka maxHR=181 は未較正だが、実測max-effortが無い以上は合理的な暫定値（過大/過小は判定不能）。「不適切」ではない
- **"Zone2" は番号ではなく身体状態（LT1未満の有酸素）を指す。何番ゾーンになるかはモデル依存**
- 新アルゴリズムの "Z2"(60-70%HRR ≒ 71-78%HRmax) はテンポ域。生理学的 Zone2 は主に新 "Z1" 側に出る → **ラベルが約1段ズレている（false friend）**
- Polarized 80/20 の "Zone2" は3ゾーンモデルの「LT1未満を80%」の意味。新 "Z2" を増やすと逆に避けるべきグレーゾーンを増やすことになる
- 研究の総意: 万人共通の %HR ＝ LT1/LT2 は存在しない。Seiler のポラライズドも閾値アンカー。固定%（Fitbitも%HRRも）は近似にすぎず、**個人のLT1を同定してHRをアンカーするのが正道**

## 設計判断

目的を **(a) LT1アンカーの "いわゆるZone2" の量を計測する** に限定する。
ポラライズド80/20管理・LT2・R-Rストラップ前提は **スコープ外**。

## 仕様

### 1. LT1 を config の単一真実にする
`config/personal.yaml` に `zone2` ブロックを追加:

```yaml
zone2:
  lt1:
    method: maf          # maf | manual（将来: dfa）
    maf_base: 180         # MAF式 base - age（暫定デフォルト）
    manual_bpm:           # Talk Test/DFA実測値。設定時は method 問わず最優先
  band_width_bpm: 15      # Zone2 = [lt1 - band_width_bpm, lt1)
```

- `manual_bpm` 未設定時は `method=maf` → `maf_base - age`（age は birth_date から既存ロジックで算出）。この個人は `180 - 39 = 141 bpm`
- 後日 Talk Test 実測値を `manual_bpm` に書くだけで上書き較正できる構造にする
- 将来拡張: 胸ストラップ+R-R で DFA-α1（α1≈0.75）から LT1 を出し `method: dfa` を追加（**今回はスコープ外**）

### 2. Zone2 の定義（狭義(ii)を採用）
**Zone2 = `[LT1 - band_width_bpm, LT1)` の心拍帯**（San Millán的「LT1直下の脂質酸化スイートスポット」）。
- 広義(i)「LT1未満すべて」は軽い歩行を混入し Fitbit と同じ過大問題を再発するため不採用
- この帯自体が安静/睡眠（<100bpm）を自然に除外するため、別途の活動フィルタは不要

### 3. 集計
- `src/lib/analytics/zone2.py`（新規モジュール。既存 hr_zones.py の %HRR 機構とは分離）
- intraday 1分HRから日別 Zone2 分を集計、日次/週次/推移を出力
- meta に lt1, method, band, age を含める

### 4. 移行検証用の参考列（任意・推奨）
較正前後の比較ができるよう、移行期は `MAF Zone2 / 現Z1 / 現Z2 / (将来)実測` を併記できる比較出力を `issues/013_zone/` に再生成する。実測値が出たとき「どの暫定が実態に近かったか」を後から検証するため。

## スコープ外

- ポラライズド 80/20、LT2、R-Rストラップ前提の処理
- DFA-α1 実装（将来 Issue）
- %HRR Z1-Z5 レポート（温存。Zone2計測とは別目的として残す）

## Acceptance Criteria

- [ ] `config/personal.yaml` に `zone2` ブロックがあり、`manual_bpm` 設定で MAF を上書きできる
- [ ] `zone2.py` が intraday から日別 Zone2 分を算出（デフォルト LT1=141, band=[126,141)）
- [ ] 90日検証で Zone2 量（日次/週次/推移）が出力され、`issues/013_zone/` に再生成される
- [ ] MAF / 現Z1 / 現Z2 の比較が併記され、後の実測較正と突合できる
- [ ] 既存の %HRR Z1-Z5 レポート・Fitbit AZM パイプラインが壊れていない
- [ ] LT1未較正・MAFは低体力者で過大傾向というリスクが README/レポートに明記される

## 将来 Issue（メモ）

- Talk Test 実測手順の整備と `manual_bpm` 更新フロー
- 胸ストラップ R-R 収集 → DFA-α1 による LT1（必要なら LT2）自動同定（`method: dfa`）
