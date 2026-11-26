# HealthPlanet API

HealthPlanet（タニタ）の取得は非公式 graph.json API（`src/lib/clients/healthplanet_unofficial.py`）だけを使う。
入口は `scripts/fetch_healthplanet.py`。

公式 OAuth API（`/status/innerscan.json`）は使わない。取れるのは体組成計だけで血圧計が無く、
認証も authorization code を手で貼る OAuth 2.0 で無人運用に向かないため。クライアントは削除済み。

---

## 非公式graph.json API (`healthplanet_unofficial.py`)

### 概要

HealthPlanetのWebサイトで使用されている内部APIを利用する非公式な方法。
公式APIより多くのデータ種類を取得可能。

**注意: 非公式な方法のため、将来使えなくなる可能性あり**

参考: https://pc.atsuhiro-me.net/entry/2023/07/22/195837

### エンドポイント

| 用途 | URL |
|-----|-----|
| ログイン画面 | `https://www.healthplanet.jp/login.do` |
| ログイン処理 | `https://www.healthplanet.jp/login_oauth.do` |
| データ取得 | `https://www.healthplanet.jp/graph/graph.json` |

### 認証方式

ID/パスワードでWebログインし、セッションCookieを使用してAPIを叩く。

```python
session = create_login_session(login_id, password)
```

### graph.json API パラメータ

| パラメータ | 説明 |
|-----------|-----|
| `day` | 取得日数（過去N日分） |
| `page` | ページ番号（通常1） |
| `kind` | データ種類番号 |

### レスポンス形式

```json
{
  "code": [0],
  "value1": [
    ["2024-01-15", 65.5],
    ["2024-01-14", 65.3]
  ]
}
```

- `code[0] == 0` で成功
- `value1` は `[日付文字列, 値]` のリスト

### 取得可能なデータ種類（kind番号）

#### 体組成計データ（デフォルト取得対象）

| kind | 列名 | 説明 |
|------|-----|-----|
| 1 | weight | 体重 (kg) |
| 2 | body_fat_rate | 体脂肪率 (%) |
| 3 | body_fat_mass | 体脂肪量 (kg) |
| 4 | visceral_fat_level | 内臓脂肪レベル |
| 5 | basal_metabolic_rate | 基礎代謝量 (kcal) |
| 6 | muscle_mass | 筋肉量 (kg) |
| 7 | bone_mass | 推定骨量 (kg) |
| 14 | body_age | 体内年齢 (才) |
| 22 | body_water_rate | 体水分率 (%) |
| 23 | muscle_quality_score | 筋質点数（全身） |

#### 全データ種類一覧

| kind | データ名 | 単位 |
|------|---------|------|
| 1 | 体組成計 - 体重 | kg |
| 2 | 体組成計 - 体脂肪率 | % |
| 3 | 体組成計 - 体脂肪量 | kg |
| 4 | 体組成計 - 内臓脂肪レベル | - |
| 5 | 体組成計 - 基礎代謝量 | kcal |
| 6 | 体組成計 - 筋肉量 | kg |
| 7 | 体組成計 - 推定骨量 | kg |
| 8 | 歩数計 - 歩数 | 歩 |
| 9 | 歩数計 - 総消費カロリー | kcal |
| 10 | 血圧計 - 血圧 | mmHg |
| 11 | 血圧計 - 脈拍 | 拍/分 |
| 13 | その他 - ウエスト | cm |
| 14 | 体組成計 - 体内年齢 | 才 |
| 15 | 血糖計 - 血糖 | mg/dL |
| 16 | 尿糖計 - 尿糖 | mg/dL |
| 17 | 歩数計 - 歩行時間 | 分 |
| 18 | 歩数計 - 活動消費カロリー | kcal |
| 20 | 歩数計 - 自転車活動カロリー | kcal |
| 21 | 歩数計 - 自転車時間 | 分 |
| 22 | 体組成計 - 体水分率 | % |
| 23 | 体組成計 - 筋質点数（全身） | - |
| 24 | 体組成計 - 筋質点数（左腕） | - |
| 25 | 体組成計 - 筋質点数（右腕） | - |
| 26 | 体組成計 - 筋質点数（左足） | - |
| 27 | 体組成計 - 筋質点数（右足） | - |
| 28 | 体組成計 - アスリート指数 | - |

### 関数

#### `create_login_session(login_id, password)`
Webログインセッションを作成。requestsのSessionオブジェクトを返す。

#### `get_innerscan_data(session, days=90, kinds=None)`
体組成計データを取得。

**引数:**
- `session`: ログイン済みセッション
- `days`: 取得日数（デフォルト90日）
- `kinds`: 取得するkind番号の辞書 `{kind: col_name}`。Noneの場合は`INNERSCAN_KINDS`を使用

**戻り値:**
```python
{
  "2024-01-15": {"weight": 65.5, "body_fat_rate": 15.2, ...},
  "2024-01-14": {"weight": 65.3, "body_fat_rate": 15.0, ...}
}
```

---

## 使用例

```python
from lib.clients.healthplanet_unofficial import create_login_session, get_innerscan_data

# ログイン
session = create_login_session("your_login_id", "your_password")

# 過去90日分のデータ取得
data = get_innerscan_data(session, days=90)

# 特定のkindのみ取得
custom_kinds = {1: 'weight', 2: 'body_fat_rate'}
data = get_innerscan_data(session, days=30, kinds=custom_kinds)
```
