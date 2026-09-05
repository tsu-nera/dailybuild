# ADR 001: 心拍ゾーンアルゴリズム

- **Status**: Accepted (2026-05-17)
- **Deciders**: tsu-nera

---

## Context

Fitbit の Active Zone Minutes (AZM) は「Fat Burn / Cardio / Peak」の3ゾーンで出力される。実データの逆算により、Fitbit の「パーソナライズゾーン」は %最大HR ではなく %HRR（カルボーネン法）であることが判明した。係数は概ね 40/60/85%HRR（39歳 / RHR≈48 / maxHR=181 の条件で ±1bpm 一致）。

bodyレポートの注記「Z2（50-69% HRmax）」は実体（%HRR）と不一致であり、ゾーン定義を統一し正確に表示する必要がある。

---

## Decision

### (1) 最大心拍数

- 推定式: Tanaka式 `208 - 0.7 × age`
- 220-age は将来精度で劣るが、39歳では両者ともに 181bpm で一致する
- 観測最大HR の自動上書きは v1 では不採用（上昇途上で境界が動くと時系列比較が破綻する）
- `config/personal.yaml` の `hr_zones.max_hr_override` に手動で実測値を投入することで上書き可能

### (2) ゾーン定義

- %HRR カルボーネン法を採用
- 5ゾーン構成、各ゾーンの下限を下記で定義:
  - Z1（回復）  : 50%HRR
  - Z2（有酸素）: 60%HRR
  - Z3（テンポ）: 70%HRR
  - Z4（閾値）  : 80%HRR
  - Z5（VO2max）: 90%HRR
- 将来的に `method: lthr`（Friel法）への切替が可能な構造とする

### (3) 安静時心拍数

- `data/wearable/heart_rate.csv` の `resting_heart_rate` 列を使用
- レポート終了日を基準とした直近 30日の中央値（期間内固定）
- レポート長に依存しない安定した値となる
- ウィンドウ内にデータが無い場合は `fallback` 値（デフォルト 48bpm）を使用

### (4) 設定ファイル

- `config/personal.yaml` を汎用個人プロファイルとして導入
- `birth_date` を単一真実とし、`age` はシステム日付から自動算出（更新不要）
- `hr_zones` 配下にゾーン関連設定をネスト

### (5) レポート表示

- レポートのゾーン表示を Z1-Z5 に完全置換
- 旧 AZM 表示（fat_burn / cardio / peak）は削除
- Fitbit AZM 取得パイプライン（fetch/parse/active_zone_minutes.csv）は温存

### (6) Fitbit AZM パイプラインの温存

- `src/lib/clients/fitbit_api.py` の `parse_active_zone_minutes`
- `src/lib/fitbit_fetcher.py` の active_zone_minutes 定義
- `data/wearable/active_zone_minutes.csv`

上記は一切変更しない。

---

## Consequences

- Fitbit の公式ゾーン値とは別系統の独自ゾーン計算になる
- Fitbit vs 独自の比較表・差分分析・ブログ分析は別 issue で対応（`active_zone_minutes.csv` 生データを入力として使用）
- レポートのゾーン境界は安静時HRの長期ドリフトに月単位で追従する
- LTHR 移行は閾値テスト実測後の後続作業となる
