# Circadian Rhythm Research - Fitbit Data Analysis

## 概要

Fitbit APIから取得した心拍数・活動量データを用いてサーカディアンリズム（概日リズム）を推定する方法の調査結果。

## 主要論文

### Circadian rhythm of heart rate and activity: A cross-sectional study (2025)

**出典**: Chronobiology International, January 2025

**研究規模**:
- 対象者: 約20,000人のFitbitユーザー（21歳以上、米国・カナダ在住）
- 期間: 30日間の連続測定
- 最終データセット: 19,350人の心拍数データ

**分析手法**: フーリエ調和解析
- **第1調和（First harmonic）**: 約24時間の周期リズムを表現
- **第2調和（Second harmonic）**: 非正弦波的な変動を補正

**測定パラメータ**:
1. **Amplitude（振幅）**: 変動の大きさ
2. **Bathyphase（浴時相）**: 心拍数が最低になる時刻
3. **Acrophase（頂時相）**: 心拍数が最高になる時刻
4. **非正弦波成分**: 第2調和から得られる波形の歪み
5. **平均値を超える心拍数の割合**: リズムの非対称性の指標

**主要な発見**:
- ほとんどの人で、心拍数のサーカディアンリズムは活動量のリズムより遅れている（位相差がある）
- パラメータは性別や年齢に依存する
- 市販のウェアラブルで長期的なサーカディアンパラメータの変化を測定可能

**参考リンク**:
- [PubMed](https://pubmed.ncbi.nlm.nih.gov/39807770/)
- [Taylor & Francis](https://www.tandfonline.com/doi/full/10.1080/07420528.2024.2446622)
- [Google Research](https://research.google/pubs/circadian-rhythm-of-heart-rate-and-activity-a-cross-sectional-study/)

## 論文から得られた数学的モデルの詳細

### 2調和フーリエモデル（論文の手法）

**出典**: Circadian rhythm of heart rate and activity (2025), Equation 1 (p.4)

**モデル式**:
```
CR(t) = μ + A₁·sin(2πt/24hr + φ₁) + A₂·sin(2πt/12hr + φ₂)
```

**パラメータ**:
- `μ`: 24時間の平均値
- `A₁`: 第1調和の振幅（24時間周期）
- `A₂`: 第2調和の振幅（12時間周期）
- `φ₁`, `φ₂`: 各調和の位相

**サーカディアン振幅**（Equation 4）:
```
A_CR = √(A₁² + A₂²)
```

**分散の寄与率**:
- **平均85.5%（男性）/ 83.7%（女性）の分散が第1調和で説明される**
- 残り約15%は第2調和が必要
- 4.9%（男性）/ 5.9%（女性）の人では第2調和の寄与が支配的

**Ultradian Rhythm指標**:
- `A₂/A₁` の比率でウルトラディアンリズムの存在を評価
- `A₂/A₁ > 1`: ウルトラディアンリズムが支配的
- 50%の人が `A₂/A₁ > 0.31`（男性）または `> 0.34`（女性）

### Fitbit APIデータの要件と前処理

**論文で使用されたデータ**（p.3-4）:

1. **心拍数（HR）データ**:
   - **Confidence = 3**（高品質PPG信号のみ）
   - 条件: PPG信号が高品質で、現在・前の1分間にステップなし
   - **加速度係数 ≤ 4**（≤0.3g、ほぼ静止状態）
   - 睡眠中のデータは除外

2. **加速度データ**:
   - 3軸加速度計（30秒ごと）
   - 各軸の範囲（最大-最小）を合計
   - 0-15の16段階にマッピング

3. **データ集約**:
   - **30日間**のデータから**1時間ごと**の平均値を計算
   - 各1時間ビン = その時間帯の30日分の平均
   - 結果: 24個の時間ビン（0時〜24時）

**最低データ要件**:
- 期間: 30日間（最低14日間のデータ）
- 1日の最低歩数: 1,000歩
- 最低装着時間: 20時間/日

## 分析手法の比較

### 1. 標準Cosinor解析（第1調和のみ）

**実装**: CosinorPyパッケージ

**モデル**:
```
y(t) = μ + β·cos(2πt/T) + γ·sin(2πt/T)
    = MESOR + Amplitude × cos(2π/T × (t - Acrophase))
```

**パラメータ定義**:
- **MESOR**: 平均値（Midline Estimating Statistic Of Rhythm）
- **Amplitude**: リズムの強度（ピークと谷の差の半分）
- **Acrophase**: ピーク時刻（位相、時間で表現）
- **Bathyphase**: 最低値の時刻
- **Period (T)**: 周期（通常24時間）

**特徴**:
- 最小二乗法でフィッティング
- 統計的有意性検定が組み込み済み
- 実装が比較的シンプル
- **約85%の分散を説明**

**長所**:
- ✅ すぐに使える（CosinorPyパッケージ）
- ✅ 統計的検定が完備
- ✅ 学習リソースが豊富

**短所**:
- ❌ 非正弦波的な変動を捉えられない
- ❌ 約15%の分散を説明できない
- ❌ ピークの非対称性を無視

### 2. 2調和フーリエモデル（論文の推奨手法）

**実装**: 手動実装が必要（scipy.optimize.curve_fitを使用）

**モデル**:
```
CR(t) = μ + A₁·sin(2πt/24 + φ₁) + A₂·sin(2πt/12 + φ₂)
```

**特徴**:
- 非正弦波的な変動を捉える
- **約98%の分散を説明**（第1調和85% + 第2調和13%）
- ピークの非対称性を表現可能

**長所**:
- ✅ 論文と同等の精度
- ✅ より正確なBathyphase/Acrophase
- ✅ Ultradian rhythmの検出可能

**短所**:
- ❌ 手動実装が必要
- ❌ 統計的検定は別途実装
- ❌ パラメータ推定がやや複雑

**どちらを使うべきか**:
- **まずCosinorPyで試す**: 基礎検証、簡単な実装
- **次に2調和モデル**: より高精度が必要な場合、論文と同等の結果が必要な場合

### 3. Extended Cosinor（拡張版）

**目的**: 非対称なパターンに対応
- 朝の急な上昇
- 日中の持続的な活動
- 夜の緩やかな低下

**実装**:
- Antilogistic変換を適用
- より柔軟な波形モデリングが可能

### 4. 心拍数特化モデル（2021年研究）

**出典**: [A method for characterizing daily physiology from widely used wearables](https://pmc.ncbi.nlm.nih.gov/articles/PMC8462795/)

**モデル式**:
```
HRₜ = a - b·cos(π/12(t-c)) + d·Activity + εₜ
```

**パラメータ**:
- `a`: 基礎心拍数（bpm）
- `b`: 24時間周期の振幅
- `c`: サーカディアンHRの最小値の時間（位相）
- `d`: 活動1単位あたりの心拍数増加量
- `εₜ`: モデル誤差（AR(1)過程でモデル化）

**誤差モデル**:
```
εₜ₊₁ = k·εₜ + N(0,σ²)
```
- `σ`: 測定誤差
- `k`: 自己相関係数

**データ処理**:
1. 心拍数と活動量を5分間隔でビニング
2. 睡眠中のデータを削除
3. 2時間未満の短い睡眠中断も除外
4. 隣接する2日間のデータを睡眠期間を中心に整理

**推定手法**: Goodman and WeareのAffine-invariant MCMCアルゴリズム
- 誤差推定を提供
- 大きなデータギャップの影響を受けにくい

### 5. 近似ベース最小二乗法（ALSM）

**出典**: [Efficient assessment of real-world dynamics of circadian rhythms](https://pmc.ncbi.nlm.nih.gov/articles/PMC10445022/)

**特徴**:
- **計算速度が約300倍高速**
- スマートフォンでの実行が可能
- 相関ノイズを持つ調和回帰モデルを独立ガウスノイズモデルに変換

**基本式**:
```
yₜ = sₜ + vₜ
```
- `yₜ`: 観測値
- `sₜ`: 信号成分（複数の調和項）
- `vₜ`: ノイズ（一次自己回帰プロセス）

**心拍データの拡張**:
- 活動効果項を追加: `d·aₜ`（ステップ数に応じた心拍増加）
- 非線形最小二乗法（Levenberg-Marquardt法）を使用

**推奨**: 単一の24時間調和項モデルが最も正確にサーカディアン位相を抽出可能

## Pythonツール

### CosinorPy（推奨）

**GitHubリポジトリ**: [mmoskon/CosinorPy](https://github.com/mmoskon/CosinorPy)

**インストール**:
```bash
pip install CosinorPy
```

**基本的な使い方**:
```python
from CosinorPy import file_parser, cosinor, cosinor1

# データ読み込み
data = file_parser.read_csv('heart_rate.csv')

# 単一成分コシノール解析
results = cosinor1.fit_cosinor(data, period=24)

# パラメータ取得
amplitude = results['amplitude']
acrophase = results['acrophase']
mesor = results['mesor']
```

**主要な4つのモジュール**:

| モジュール | 機能 |
|----------|------|
| `file_parser` | xlsx/csvファイルの読み書き、合成データ生成 |
| `cosinor` | 単一・複数成分のコシノール関数 |
| `cosinor1` | 単一成分コシノール専用機能 |
| `cosinor_nonlin` | 一般化コシノール模型と非線形回帰分析 |

**機能**:
- 前処理（外れ値除去、線形トレンド除去、時間間隔フィルタリング）
- 単一・複数成分コシノール解析
- 非線形回帰
- 統計的検定（振幅検出、信頼区間推定、周期分析）
- 独立測定値・従属測定値・ポアソン回帰データ対応

**学習リソース**:
- 9つのJupyter Notebookサンプル
- 独立データ・従属データ・非線形分析など複数のシナリオ

**ライセンス**: MIT

**参考文献**:
- [CosinorPy: a python package for cosinor-based rhythmometry](https://link.springer.com/article/10.1186/s12859-020-03830-w)

### その他のPythonパッケージ

**HRV分析ツール**:
- **hrv-analysis**: HRV（心拍変動）分析用
  - [PyPI](https://pypi.org/project/hrv-analysis/)
- **wearable-hrv**: ウェアラブル専用のHRV検証ツール
  - [GitHub](https://github.com/Aminsinichi/wearable-hrv)
- **pyHRV**: 総合的なHRV解析ツール
  - [GitHub](https://github.com/PGomes92/pyhrv)
  - [Documentation](https://pyhrv.readthedocs.io/)

**参考文献**:
- [A Python Package for Heart Rate Variability Analysis](https://openresearchsoftware.metajnl.com/articles/10.5334/jors.305)

### GGIRパッケージ（R言語）

**参考**: [GGIR - Circadian Rhythm Analysis](https://wadpac.github.io/GGIR/articles/chapter13_CircadianRhythm.html)

- Cosinor解析とExtended Cosinor解析をサポート
- ログ変換された時系列に対するコサイン関数フィッティング

## 実装プラン（このプロジェクト向け）

### 必要なFitbitデータ

既に取得済みと思われるデータ:
1. **Intraday Heart Rate**（1分または5分間隔）
   - ファイル: `data/fitbit/heart_rate.csv`
2. **Activity/Steps**（活動量）
   - ファイル: `data/fitbit/activity.csv`
3. **Sleep Data**（睡眠時刻）
   - ファイル: `data/fitbit/sleep.csv`

### 基本的な処理フロー

```python
# 1. データ前処理
# - 5分間隔で平均化（リサンプリング）
# - 睡眠中のデータを除外
# - 欠損値の処理（線形補間または除外）

# 2. コシノールモデルのフィッティング
# 基本モデル:
# HRₜ = MESOR + Amplitude × cos(2π/24 × (t - Acrophase))

# 活動量を考慮したモデル:
# HRₜ = a - b·cos(π/12(t-c)) + d·Activity + εₜ

# 3. パラメータ抽出
# - MESOR: 平均心拍数
# - Amplitude: リズムの強度
# - Acrophase: ピーク時刻
# - Bathyphase: 最低時刻

# 4. 可視化
# - 元データとフィッティング曲線のプロット
# - パラメータの時系列変化
# - 信頼区間の表示
```

### 推奨アプローチ

1. **Phase 1: CosinorPyで基本分析**
   - `CosinorPy`をインストール
   - `heart_rate.csv`で単純なコシノール解析
   - Amplitude、Acrophase、MESORを算出・可視化

2. **Phase 2: 活動量の影響を考慮**
   - 活動量データを統合
   - 心拍数 = サーカディアン成分 + 活動由来成分
   - より精密なサーカディアンリズム抽出

3. **Phase 3: プロジェクトへの統合**
   - `src/lib/analytics/circadian.py`を作成
   - レポート生成スクリプトに組み込み
   - `reports/circadian/`にレポート出力

### サンプル実装: 両方の手法

```python
# src/lib/analytics/circadian.py
import pandas as pd
import numpy as np
from scipy.optimize import curve_fit

class CircadianRhythmAnalyzer:
    """
    Fitbit心拍数データからサーカディアンリズムを抽出

    2つの手法をサポート:
    1. CosinorPyによる標準Cosinor解析（第1調和のみ）
    2. 2調和フーリエモデル（論文の手法）
    """

    def __init__(self, method='cosinor'):
        """
        Parameters:
        -----------
        method : str
            'cosinor' - 第1調和のみ（CosinorPy、簡単）
            'two_harmonic' - 第1+第2調和（論文の手法、高精度）
        """
        self.method = method

    def prepare_hr_data(self, heart_rate_df, sleep_df=None,
                       confidence_threshold=3,
                       acceleration_threshold=4):
        """
        論文の手法に従ってHRデータを前処理

        Parameters:
        -----------
        heart_rate_df : pd.DataFrame
            心拍数データ（datetime index, 'heart_rate', 'confidence', 'acceleration'列）
        sleep_df : pd.DataFrame, optional
            睡眠データ（睡眠中のデータ除外用）
        confidence_threshold : int, default=3
            PPG信号の品質閾値（論文では3 = 高品質のみ）
        acceleration_threshold : int, default=4
            加速度係数の閾値（論文では≤4 = ≤0.3g）

        Returns:
        --------
        np.ndarray : 24個の1時間平均心拍数（0時〜23時）
        """
        # 1. 論文のフィルタリング条件を適用
        hr_filtered = heart_rate_df.copy()

        if 'confidence' in hr_filtered.columns:
            hr_filtered = hr_filtered[hr_filtered['confidence'] >= confidence_threshold]

        if 'acceleration' in hr_filtered.columns:
            hr_filtered = hr_filtered[hr_filtered['acceleration'] <= acceleration_threshold]

        # 2. 睡眠中のデータを除外
        if sleep_df is not None:
            hr_filtered = self._exclude_sleep_periods(hr_filtered, sleep_df)

        # 3. 30日間のデータから1時間ごとの平均を計算
        hourly_means = []
        for hour in range(24):
            hour_data = hr_filtered[hr_filtered.index.hour == hour]
            if len(hour_data) > 0:
                hourly_means.append(hour_data['heart_rate'].mean())
            else:
                hourly_means.append(np.nan)

        return np.array(hourly_means)

    def fit(self, hourly_hr_data):
        """サーカディアンリズムをフィッティング"""
        if self.method == 'two_harmonic':
            return self._fit_two_harmonic(hourly_hr_data)
        else:
            return self._fit_cosinor(hourly_hr_data)

    def _fit_cosinor(self, hourly_hr_data):
        """
        標準Cosinor解析（第1調和のみ）
        CosinorPyを使用
        """
        from CosinorPy import cosinor1

        # データ準備
        t = np.arange(24)
        valid_mask = ~np.isnan(hourly_hr_data)

        # CosinorPyでフィッティング
        # 注意: CosinorPyの実際のAPIに合わせて調整が必要
        data = pd.DataFrame({'x': t[valid_mask], 'y': hourly_hr_data[valid_mask]})
        results, amp, acr, statistics = cosinor1.fit_cosinor(
            data['x'].values,
            data['y'].values,
            period=24,
            plot_on=False
        )

        return {
            'method': 'cosinor',
            'mu': results.params['Intercept'],
            'A1': amp,
            'phi1': acr,
            'A2': 0,  # 第2調和なし
            'phi2': 0,
            'A_CR': amp,
            'bathyphase': self._calculate_bathyphase_cosinor(results.params['Intercept'], amp, acr),
            'acrophase': self._calculate_acrophase_cosinor(acr),
            'p_value': results.f_pvalue,
            'r_squared': results.rsquared,
            'A2_A1_ratio': 0,
        }

    def _fit_two_harmonic(self, hourly_hr_data):
        """
        2調和フーリエモデル（論文の手法）
        scipy.optimize.curve_fitを使用
        """
        def model(t, mu, A1, phi1, A2, phi2):
            """論文のEquation 1"""
            return (mu +
                    A1 * np.sin(2*np.pi*t/24 + phi1) +
                    A2 * np.sin(2*np.pi*t/12 + phi2))

        t = np.arange(24)
        valid_mask = ~np.isnan(hourly_hr_data)
        t_valid = t[valid_mask]
        y_valid = hourly_hr_data[valid_mask]

        # 初期推定値
        mu_init = np.nanmean(hourly_hr_data)
        A1_init = (np.nanmax(hourly_hr_data) - np.nanmin(hourly_hr_data)) / 2
        phi1_init = 0
        A2_init = A1_init / 4  # 第2調和は第1調和より小さい
        phi2_init = 0

        p0 = [mu_init, A1_init, phi1_init, A2_init, phi2_init]

        # フィッティング
        popt, pcov = curve_fit(model, t_valid, y_valid, p0=p0)

        mu, A1, phi1, A2, phi2 = popt

        # サーカディアン振幅（Equation 4）
        A_CR = np.sqrt(A1**2 + A2**2)

        # Bathyphase & Acrophase（数値的に計算）
        hr_curve = model(t, *popt)
        bathyphase = t[np.argmin(hr_curve)]
        acrophase = t[np.argmax(hr_curve)]

        # 統計量
        fitted = model(t_valid, *popt)
        ss_total = np.sum((y_valid - np.mean(y_valid))**2)
        ss_residual = np.sum((y_valid - fitted)**2)
        r_squared = 1 - (ss_residual / ss_total)

        # 第1調和のみの寄与率
        fitted_1st_only = mu + A1 * np.sin(2*np.pi*t_valid/24 + phi1)
        ss_1st = np.sum((fitted_1st_only - mu)**2)
        variance_1st_pct = ss_1st / ss_total * 100

        return {
            'method': 'two_harmonic',
            'mu': mu,
            'A1': A1,
            'phi1': phi1,
            'A2': A2,
            'phi2': phi2,
            'A_CR': A_CR,
            'bathyphase': bathyphase,
            'acrophase': acrophase,
            'r_squared': r_squared,
            'variance_1st_harmonic_pct': variance_1st_pct,
            'A2_A1_ratio': A2 / A1,
        }

    def _exclude_sleep_periods(self, hr_df, sleep_df):
        """睡眠中のデータを除外"""
        # 実装: 睡眠時刻のデータをマスク
        # sleep_dfから睡眠時刻を取得し、該当時刻のデータを除外
        return hr_df

    def _calculate_bathyphase_cosinor(self, mesor, amp, acr):
        """Cosinorモデルから最低時刻を計算"""
        # acrophaseから12時間後
        return (acr + 12) % 24

    def _calculate_acrophase_cosinor(self, acr):
        """Cosinorモデルから最高時刻を計算"""
        # acrをラジアンから時間に変換
        return (-acr * 24 / (2*np.pi)) % 24


# 使用例
def example_usage():
    """使用例"""
    # データ読み込み
    hr_df = pd.read_csv('data/fitbit/heart_rate.csv', index_col='datetime', parse_dates=True)
    sleep_df = pd.read_csv('data/fitbit/sleep.csv', parse_dates=True)

    # 1. CosinorPyで試す（簡単）
    analyzer_cosinor = CircadianRhythmAnalyzer(method='cosinor')
    hourly_hr = analyzer_cosinor.prepare_hr_data(hr_df, sleep_df)
    results_cosinor = analyzer_cosinor.fit(hourly_hr)

    print("=== Cosinor解析結果 ===")
    print(f"MESOR: {results_cosinor['mu']:.1f} bpm")
    print(f"Amplitude: {results_cosinor['A_CR']:.1f} bpm")
    print(f"Acrophase: {results_cosinor['acrophase']:.1f} hr")
    print(f"R²: {results_cosinor['r_squared']:.3f}")

    # 2. 2調和モデルで試す（高精度）
    analyzer_2h = CircadianRhythmAnalyzer(method='two_harmonic')
    results_2h = analyzer_2h.fit(hourly_hr)

    print("\n=== 2調和モデル結果 ===")
    print(f"MESOR: {results_2h['mu']:.1f} bpm")
    print(f"Amplitude (A_CR): {results_2h['A_CR']:.1f} bpm")
    print(f"  - A1 (24hr): {results_2h['A1']:.1f} bpm")
    print(f"  - A2 (12hr): {results_2h['A2']:.1f} bpm")
    print(f"  - A2/A1 ratio: {results_2h['A2_A1_ratio']:.3f}")
    print(f"Bathyphase: {results_2h['bathyphase']:.1f} hr")
    print(f"Acrophase: {results_2h['acrophase']:.1f} hr")
    print(f"R²: {results_2h['r_squared']:.3f}")
    print(f"第1調和の寄与: {results_2h['variance_1st_harmonic_pct']:.1f}%")
```

## 論文から得られた数値データ

### サーカディアンパラメータの平均値（年齢別）

**振幅（A_CR）**:

| 年齢 | 男性 (bpm) | 女性 (bpm) | 効果量 (d) |
|------|-----------|-----------|-----------|
| 21-30 | 7.6 ± 2.8 | 6.2 ± 2.5 | 0.54 |
| 31-40 | 7.3 ± 2.7 | 5.8 ± 2.4 | 0.61 |
| 41-50 | 6.9 ± 2.9 | 5.4 ± 2.2 | 0.63 |
| 51-60 | 6.3 ± 2.4 | 5.4 ± 2.2 | 0.40 |
| 61-70 | 5.5 ± 2.4 | 5.2 ± 2.1 | <0.2 |

**年齢との相関**:
- 男性: r = -0.26 (p<0.0001)
- 女性: r = -0.13 (p<0.0001)

**Bathyphaseと起床時刻の相関**:
- 男性: r = 0.44 (p<0.0001)
- 女性: r = 0.36 (p<0.0001)

**心拍数-活動量の位相差（ラグ）**:
- 男性: 2.0時間（心拍が遅れる）
- 女性: 2.6時間（心拍が遅れる）
- 効果量: d = 0.26 (p<0.0001)

**位相関係**:
- 86.6%の人: Bathyphase < Wake time（心拍最低が起床前）
  - 中央値: 2.32時間の差
  - 四分位範囲: 1.08 - 3.27時間
- 91.8%の人: Acrophase < Bedtime（心拍最高が就寝前）
  - 中央値: 5.86時間の差
  - 四分位範囲: 3.35 - 8.78時間

## 参考文献まとめ

### 主要論文

1. **Circadian rhythm of heart rate and activity: A cross-sectional study** (2025)
   - Chronobiology International
   - [PubMed](https://pubmed.ncbi.nlm.nih.gov/39807770/)

2. **A method for characterizing daily physiology from widely used wearables** (2021)
   - Cell Reports Methods
   - [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8462795/)

3. **Efficient assessment of real-world dynamics of circadian rhythms** (2023)
   - Journal of The Royal Society Interface
   - [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10445022/)

4. **Circadian Rhythm Analysis Using Wearable Device Data** (2021)
   - JMIR
   - [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8554674/)

5. **Detection and Analysis of Circadian Biomarkers for Metabolic Syndrome** (2024)
   - JMIR Medical Informatics
   - [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12311872/)

### ツール・パッケージ

1. **CosinorPy**
   - [GitHub](https://github.com/mmoskon/CosinorPy)
   - [論文](https://link.springer.com/article/10.1186/s12859-020-03830-w)

2. **GGIR (R)**
   - [Documentation](https://wadpac.github.io/GGIR/articles/chapter13_CircadianRhythm.html)

3. **HRV Analysis Tools**
   - [hrv-analysis (Python)](https://pypi.org/project/hrv-analysis/)
   - [wearable-hrv (Python)](https://github.com/Aminsinichi/wearable-hrv)
   - [pyHRV (Python)](https://github.com/PGomes92/pyhrv)

## 実装ロードマップ

### Phase 1: CosinorPyで基礎検証（まずここから）

**目的**: 基本的なサーカディアンリズムの存在を確認

1. **環境準備**:
   ```bash
   pip install CosinorPy scipy matplotlib
   ```

2. **データ確認**:
   - `data/fitbit/heart_rate.csv`のフォーマット確認
   - Confidence値、加速度データの有無を確認
   - データ期間（最低30日間あるか）

3. **基本実装**:
   - `src/lib/analytics/circadian.py`を作成
   - CosinorPyを使った第1調和モデルを実装
   - 24時間の心拍数平均を可視化

4. **期待される結果**:
   - Amplitude: 5-7 bpm程度（年齢・性別により変動）
   - R²: 0.7-0.85程度（第1調和で約85%の分散を説明）
   - P-value < 0.05（統計的有意性）

### Phase 2: 2調和モデルで高精度化（CosinorPyで問題なければ）

**目的**: 論文と同等の精度でサーカディアンリズムを抽出

1. **2調和モデルの実装**:
   - `scipy.optimize.curve_fit`を使用
   - 論文のEquation 1を実装
   - Bathyphase/Acrophaseを数値的に計算

2. **比較分析**:
   - Cosinor vs 2調和モデルの結果を比較
   - R²の向上を確認（0.85 → 0.95+を期待）
   - `A₂/A₁`比率を確認（論文では中央値0.31-0.34）

3. **期待される改善**:
   - より正確なBathyphase/Acrophaseの推定
   - 非正弦波的な変動の捕捉
   - 約15%の分散説明率の向上

### Phase 3: レポート生成とプロジェクト統合

**目的**: 日次/週次レポートに組み込む

1. **レポート生成スクリプト**:
   - `scripts/generate_circadian_report_daily.py`を作成
   - Jinja2テンプレートでMarkdownレポート生成
   - グラフ可視化（matplotlib）

2. **テンプレート作成**:
   - `templates/circadian/base.md.j2`
   - `templates/circadian/daily_report.md.j2`
   - セクション: サマリー、パラメータ、グラフ、解釈

3. **出力例**:
   ```markdown
   # サーカディアンリズム分析レポート

   ## 基本パラメータ
   - MESOR: 65.3 bpm
   - Amplitude: 6.8 bpm
   - Acrophase: 16:30 (午後4時30分)
   - Bathyphase: 4:15 (午前4時15分)

   ## 評価
   - サーカディアンリズムは明確に検出されました (p<0.001)
   - 振幅は年齢相応の範囲内です
   - 起床時刻との位相差: 2.1時間
   ```

### Phase 4: 高度な分析（オプション）

**目的**: より深い洞察を得る

1. **活動量との関係分析**:
   - 心拍数-活動量の位相差計算
   - ラグ時間の推定（論文では2-2.6時間）

2. **時系列変化の追跡**:
   - スライディングウィンドウで日々の変化を観察
   - 季節変動、生活習慣変化の影響を分析

3. **睡眠品質との相関**:
   - Bathyphaseと起床時刻の関係
   - 睡眠の質とサーカディアンリズムの強度

## 重要な注意点

### Fitbit APIの制限について

**確認済み**:
- ✅ 心拍数（HR）データは取得可能
- ✅ 論文ではHRVは使用していない（HRのみ）
- ✅ Confidence値、加速度データの取得状況を確認すること

**未確認**:
- ❓ Fitbit APIからConfidence値が取得できるか？
- ❓ 加速度データが利用可能か？

**対策**:
- Confidence値がない場合: 睡眠中のデータ除外で代替
- 加速度データがない場合: ステップ数で活動量を推定

### データ品質の確保

**最低要件**:
- 30日間のデータ（最低14日間）
- 1日20時間以上の装着
- 1日1,000歩以上の活動

**データ欠損への対処**:
- 欠損時間が多い日は除外
- 時間帯ごとの欠損は線形補間または除外
- 最低でも各時間帯に7日分のデータがあることを推奨

## 次のアクション

1. ✅ **research.mdの更新完了**
2. ⬜ CosinorPyをインストール
3. ⬜ `data/fitbit/heart_rate.csv`のデータ構造を確認
4. ⬜ `src/lib/analytics/circadian.py`の基本実装
5. ⬜ Cosinor解析の実行とパラメータ確認
6. ⬜ 結果が妥当なら2調和モデルへ拡張
7. ⬜ レポート生成機能の実装
