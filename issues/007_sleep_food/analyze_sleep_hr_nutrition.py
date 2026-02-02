#!/usr/bin/env python
# coding: utf-8
"""
睡眠中の心拍数と食事の関係を分析するスクリプト

既存の睡眠心拍数分析ライブラリを活用して、栄養データとの相関を分析します。

Usage:
    python scripts/analyze_sleep_hr_nutrition.py [--output <DIR>] [--days <N>]
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# プロジェクトルートをパスに追加
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib.analytics import sleep
from lib.utils.report_args import add_common_report_args

# データファイルパス
BASE_DIR = project_root
SLEEP_CSV = BASE_DIR / 'data/fitbit/sleep.csv'
NUTRITION_CSV = BASE_DIR / 'data/fitbit/nutrition.csv'
HR_INTRADAY_CSV = BASE_DIR / 'data/fitbit/heart_rate_intraday.csv'
HR_DAILY_CSV = BASE_DIR / 'data/fitbit/heart_rate.csv'


def load_and_merge_hr_nutrition_data(days=None):
    """
    睡眠心拍数データと栄養データを読み込んで結合

    Parameters
    ----------
    days : int, optional
        分析対象の日数

    Returns
    -------
    pd.DataFrame
        結合されたデータフレーム
    """
    print('データ読み込み中...')

    # 睡眠データ読み込み（主睡眠のみ）
    df_sleep = pd.read_csv(SLEEP_CSV)
    df_sleep = df_sleep[df_sleep['isMainSleep'] == True].copy()
    df_sleep['dateOfSleep'] = pd.to_datetime(df_sleep['dateOfSleep'])

    # 栄養データ読み込み
    df_nutrition = pd.read_csv(NUTRITION_CSV)
    df_nutrition['date'] = pd.to_datetime(df_nutrition['date'])
    df_nutrition = df_nutrition[df_nutrition['calories'] > 0].copy()

    # 心拍数データ読み込み
    print(f'Loading: {HR_INTRADAY_CSV}')
    df_hr_intraday = pd.read_csv(HR_INTRADAY_CSV)

    print(f'Loading: {HR_DAILY_CSV}')
    df_hr_daily = pd.read_csv(HR_DAILY_CSV)

    # 日数でフィルタリング
    if days is not None:
        end_date = df_sleep['dateOfSleep'].max()
        start_date = end_date - pd.Timedelta(days=days)
        df_sleep = df_sleep[df_sleep['dateOfSleep'] >= start_date]
        df_nutrition = df_nutrition[df_nutrition['date'] >= start_date]

    print(f'  睡眠データ: {len(df_sleep)}日分')
    print(f'  栄養データ: {len(df_nutrition)}日分（記録あり）')

    # 睡眠中の心拍数統計を計算
    print('計算中: 睡眠中の心拍数統計...')
    hr_stats = sleep.calc_sleep_heart_rate_stats(
        df_sleep, df_hr_intraday, df_hr_daily, baseline_days=7
    )

    # 高度な心拍数指標を計算
    print('計算中: 高度な心拍数指標（ディップ率、最低HR到達時間）...')
    advanced_hr = sleep.calc_advanced_hr_metrics(df_sleep, df_hr_intraday)

    # データ結合: 栄養データの翌日の睡眠心拍数と紐付け
    merged_list = []
    for _, nutr_row in df_nutrition.iterrows():
        nutrition_date = nutr_row['date']
        sleep_date = nutrition_date + pd.Timedelta(days=1)

        # 対応する睡眠データを検索
        sleep_rows = df_sleep[df_sleep['dateOfSleep'] == sleep_date]
        if len(sleep_rows) > 0 and sleep_date in hr_stats:
            sleep_row = sleep_rows.iloc[0]
            hr_stat = hr_stats[sleep_date]
            adv_hr = advanced_hr.get(sleep_date, {})

            merged_list.append({
                'nutrition_date': nutrition_date,
                'sleep_date': sleep_date,
                # 栄養素
                'calories': nutr_row['calories'],
                'carbs': nutr_row['carbs'],
                'fat': nutr_row['fat'],
                'fiber': nutr_row['fiber'],
                'protein': nutr_row['protein'],
                'sodium': nutr_row['sodium'],
                'water': nutr_row['water'],
                # 睡眠基本指標
                'sleep_minutes': sleep_row['minutesAsleep'],
                'sleep_efficiency': sleep_row['efficiency'],
                'deep_minutes': sleep_row['deepMinutes'],
                'rem_minutes': sleep_row['remMinutes'],
                # 心拍数指標
                'avg_hr': hr_stat['avg_hr'],
                'min_hr': hr_stat['min_hr'],
                'max_hr': hr_stat['max_hr'],
                'daily_resting_hr': hr_stat.get('daily_resting_hr', np.nan),
                'above_baseline_pct': hr_stat.get('above_baseline_pct', np.nan),
                'below_baseline_pct': hr_stat.get('below_baseline_pct', np.nan),
                # 高度な指標
                'dip_rate': adv_hr.get('dip_rate_avg', np.nan),
                'time_to_min_hr': adv_hr.get('time_to_min_hr', np.nan),
            })

    df_merged = pd.DataFrame(merged_list)
    print(f'  結合データ: {len(df_merged)}日分')

    return df_merged


def calc_hr_correlation_analysis(df):
    """
    心拍数と栄養素の相関分析

    Parameters
    ----------
    df : pd.DataFrame
        結合データ

    Returns
    -------
    dict
        分析結果
    """
    print('相関分析中...')

    nutrients = ['calories', 'carbs', 'fat', 'fiber', 'protein', 'sodium']
    hr_metrics = ['avg_hr', 'min_hr', 'max_hr', 'dip_rate', 'time_to_min_hr',
                  'above_baseline_pct', 'below_baseline_pct']

    # NaN値を除外して相関計算
    corr = df[nutrients + hr_metrics].corr()
    hr_nutrition_corr = corr.loc[hr_metrics, nutrients]

    # 最も相関の強い組み合わせを抽出
    abs_corr = hr_nutrition_corr.abs()
    max_correlations = {}
    for metric in hr_metrics:
        if not abs_corr.loc[metric].isna().all():
            max_nutrient = abs_corr.loc[metric].idxmax()
            max_correlations[metric] = {
                'nutrient': max_nutrient,
                'value': corr.loc[metric, max_nutrient]
            }

    return {
        'correlation_matrix': hr_nutrition_corr,
        'max_correlations': max_correlations
    }


def create_hr_category_analysis(df):
    """
    カテゴリ別の心拍数分析

    Parameters
    ----------
    df : pd.DataFrame
        結合データ

    Returns
    -------
    dict
        カテゴリ別統計
    """
    print('カテゴリ別分析中...')

    # カロリー区分
    df['calorie_category'] = pd.cut(df['calories'],
                                      bins=[0, 1000, 1500, 2000, 5000],
                                      labels=['低(~1000)', '中(1000-1500)',
                                             '高(1500-2000)', '過多(2000~)'])

    calorie_stats = df.groupby('calorie_category', observed=True)[
        ['avg_hr', 'min_hr', 'dip_rate', 'time_to_min_hr']
    ].agg(['mean', 'count'])

    # タンパク質区分
    df['protein_category'] = pd.cut(df['protein'],
                                      bins=[0, 50, 80, 120, 200],
                                      labels=['低(~50g)', '中(50-80g)',
                                             '高(80-120g)', '過多(120g~)'])

    protein_stats = df.groupby('protein_category', observed=True)[
        ['avg_hr', 'min_hr', 'dip_rate', 'time_to_min_hr']
    ].agg(['mean', 'count'])

    return {
        'calorie_stats': calorie_stats,
        'protein_stats': protein_stats
    }


def plot_hr_correlation_heatmap(corr_matrix, save_path):
    """
    心拍数と栄養素の相関ヒートマップ

    Parameters
    ----------
    corr_matrix : pd.DataFrame
        相関係数行列
    save_path : Path
        保存先パス
    """
    print('プロット中: 心拍数相関ヒートマップ...')

    plt.figure(figsize=(10, 8))
    sns.heatmap(corr_matrix, annot=True, fmt='.3f', cmap='coolwarm',
                center=0, vmin=-1, vmax=1, cbar_kws={'label': '相関係数'})
    plt.title('栄養素と睡眠中の心拍数指標の相関係数', fontsize=14, pad=20)
    plt.xlabel('栄養素', fontsize=12)
    plt.ylabel('心拍数指標', fontsize=12)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()


def plot_hr_scatter_analysis(df, save_path):
    """
    心拍数と栄養素の散布図

    Parameters
    ----------
    df : pd.DataFrame
        結合データ
    save_path : Path
        保存先パス
    """
    print('プロット中: 心拍数散布図...')

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle('栄養素と平均心拍数の関係', fontsize=14)

    nutrients = ['calories', 'carbs', 'fat', 'fiber', 'protein', 'sodium']
    for i, nutrient in enumerate(nutrients):
        ax = axes[i // 3, i % 3]

        # NaN値を除外
        mask = ~(df[nutrient].isna() | df['avg_hr'].isna())
        x_data = df.loc[mask, nutrient]
        y_data = df.loc[mask, 'avg_hr']

        if len(x_data) > 0:
            ax.scatter(x_data, y_data, alpha=0.6)

            # 回帰直線
            if len(x_data) > 1:
                z = np.polyfit(x_data, y_data, 1)
                p = np.poly1d(z)
                ax.plot(x_data, p(x_data), "r--", alpha=0.8)

            # 相関係数を表示
            corr = x_data.corr(y_data)
            ax.set_title(f'{nutrient} (r={corr:.3f})')
        else:
            ax.set_title(f'{nutrient} (データなし)')

        ax.set_xlabel(nutrient)
        ax.set_ylabel('平均心拍数(bpm)')
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()


def plot_dip_rate_analysis(df, save_path):
    """
    ディップ率と栄養素の関係

    Parameters
    ----------
    df : pd.DataFrame
        結合データ
    save_path : Path
        保存先パス
    """
    print('プロット中: ディップ率分析...')

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle('ディップ率と栄養素の関係', fontsize=14)

    # カロリーとディップ率
    mask = ~(df['calories'].isna() | df['dip_rate'].isna())
    if mask.sum() > 0:
        ax = axes[0]
        x_data = df.loc[mask, 'calories']
        y_data = df.loc[mask, 'dip_rate']
        ax.scatter(x_data, y_data, alpha=0.6)

        if len(x_data) > 1:
            z = np.polyfit(x_data, y_data, 1)
            p = np.poly1d(z)
            ax.plot(x_data, p(x_data), "r--", alpha=0.8)

        corr = x_data.corr(y_data)
        ax.set_title(f'カロリー vs ディップ率 (r={corr:.3f})')
        ax.set_xlabel('カロリー(kcal)')
        ax.set_ylabel('ディップ率(%)')
        ax.grid(True, alpha=0.3)

    # タンパク質とディップ率
    mask = ~(df['protein'].isna() | df['dip_rate'].isna())
    if mask.sum() > 0:
        ax = axes[1]
        x_data = df.loc[mask, 'protein']
        y_data = df.loc[mask, 'dip_rate']
        ax.scatter(x_data, y_data, alpha=0.6)

        if len(x_data) > 1:
            z = np.polyfit(x_data, y_data, 1)
            p = np.poly1d(z)
            ax.plot(x_data, p(x_data), "r--", alpha=0.8)

        corr = x_data.corr(y_data)
        ax.set_title(f'タンパク質 vs ディップ率 (r={corr:.3f})')
        ax.set_xlabel('タンパク質(g)')
        ax.set_ylabel('ディップ率(%)')
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()


def generate_markdown_report(output_dir, df, corr_analysis, category_analysis):
    """
    心拍数と栄養のMarkdownレポートを生成

    Parameters
    ----------
    output_dir : Path
        出力ディレクトリ
    df : pd.DataFrame
        結合データ
    corr_analysis : dict
        相関分析結果
    category_analysis : dict
        カテゴリ別分析結果
    """
    print('レポート生成中...')

    report_path = output_dir / 'HR_NUTRITION_ANALYSIS.md'

    with open(report_path, 'w', encoding='utf-8') as f:
        # ヘッダー
        f.write("# 睡眠中の心拍数と食事の関係分析レポート\n\n")
        f.write(f"**生成日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("---\n\n")

        # データサマリー
        f.write("## 📊 データサマリー\n\n")
        f.write(f"- **分析対象**: {len(df)}日分のデータ\n")
        f.write(f"- **期間**: {df['nutrition_date'].min().strftime('%Y-%m-%d')} ~ "
                f"{df['nutrition_date'].max().strftime('%Y-%m-%d')}\n")
        f.write("- **分析内容**: 食事記録の翌日の睡眠中の心拍数データとの相関分析\n\n")

        # 心拍数の基本統計
        f.write("## ❤️ 睡眠中の心拍数統計\n\n")
        f.write("| 指標 | 平均心拍数(bpm) | 最低心拍数(bpm) | 最高心拍数(bpm) | ディップ率(%) | 最低HR到達(分) |\n")
        f.write("|------|-----------------|-----------------|-----------------|---------------|----------------|\n")

        hr_cols = ['avg_hr', 'min_hr', 'max_hr', 'dip_rate', 'time_to_min_hr']
        for label in ['平均', '中央値', '最小', '最大']:
            f.write(f"| {label} | ")
            values = []
            for col in hr_cols:
                if label == '平均':
                    val = f"{df[col].mean():.1f}"
                elif label == '中央値':
                    val = f"{df[col].median():.1f}"
                elif label == '最小':
                    val = f"{df[col].min():.1f}"
                else:  # 最大
                    val = f"{df[col].max():.1f}"
                values.append(val)
            f.write(" | ".join(values))
            f.write(" |\n")
        f.write("\n")

        # 心拍数指標の説明
        f.write("### 指標の説明\n\n")
        f.write("- **平均心拍数**: 睡眠中の心拍数の平均値\n")
        f.write("- **最低心拍数**: 睡眠中の最低心拍数（通常は深い睡眠時に記録）\n")
        f.write("- **ディップ率**: 日中の安静時心拍数から睡眠中にどれだけ心拍数が低下したか\n")
        f.write("  - 健康的な値: 10-20%の低下\n")
        f.write("  - 高い値ほど良好な回復を示す\n")
        f.write("- **最低HR到達時間**: 入眠からどれくらいで最低心拍数に到達したか（分）\n")
        f.write("  - 早いほど良好な回復を示す\n\n")

        # 相関分析
        f.write("## 🔗 栄養素と心拍数の相関分析\n\n")
        f.write("### 相関係数マトリックス\n\n")
        f.write("相関係数は-1~1の範囲。**絶対値が0.3以上**で中程度、**0.5以上**で強い相関。\n\n")

        corr_matrix = corr_analysis['correlation_matrix']
        nutrients = corr_matrix.columns.tolist()

        # テーブルヘッダー
        f.write("| 心拍数指標 | ")
        f.write(" | ".join(nutrients))
        f.write(" |\n")
        f.write("|" + "---|" * (len(nutrients) + 1) + "\n")

        # 相関係数テーブル
        hr_metric_names = {
            'avg_hr': '平均心拍数',
            'min_hr': '最低心拍数',
            'max_hr': '最高心拍数',
            'dip_rate': 'ディップ率',
            'time_to_min_hr': '最低HR到達時間',
            'above_baseline_pct': 'ベースライン超過%',
            'below_baseline_pct': 'ベースライン未満%'
        }

        for metric in corr_matrix.index:
            f.write(f"| {hr_metric_names.get(metric, metric)} |")
            for nutrient in nutrients:
                val = corr_matrix.loc[metric, nutrient]
                if pd.isna(val):
                    f.write(" - |")
                elif abs(val) >= 0.3:
                    f.write(f" **{val:.3f}** |")
                else:
                    f.write(f" {val:.3f} |")
            f.write("\n")
        f.write("\n")

        # ヒートマップ画像
        f.write("### 相関ヒートマップ\n\n")
        f.write("![相関ヒートマップ](img/hr_correlation_heatmap.png)\n\n")

        # 散布図
        f.write("### 散布図分析\n\n")
        f.write("![散布図](img/hr_scatter_analysis.png)\n\n")

        # ディップ率分析
        f.write("### ディップ率分析\n\n")
        f.write("![ディップ率](img/dip_rate_analysis.png)\n\n")

        # 最も相関の強い組み合わせ
        f.write("## 📈 主な発見\n\n")
        max_corrs = corr_analysis['max_correlations']
        for metric, data in max_corrs.items():
            metric_name = hr_metric_names.get(metric, metric)
            nutrient = data['nutrient']
            value = data['value']
            if not pd.isna(value):
                direction = "正の相関" if value > 0 else "負の相関"
                strength = "強い" if abs(value) >= 0.5 else "中程度の" if abs(value) >= 0.3 else "弱い"
                f.write(f"- **{metric_name}**: {nutrient}と{strength}{direction} (r={value:.3f})\n")
        f.write("\n")

        # カテゴリ別分析
        f.write("## 📊 カテゴリ別分析\n\n")

        # カロリー別
        f.write("### カロリー摂取量別の心拍数\n\n")
        f.write("| カロリー区分 | データ数 | 平均心拍数 | 最低心拍数 | ディップ率(%) | 最低HR到達(分) |\n")
        f.write("|--------------|----------|------------|------------|---------------|----------------|\n")

        calorie_stats = category_analysis['calorie_stats']
        for cat in calorie_stats.index:
            count = int(calorie_stats.loc[cat, ('avg_hr', 'count')])
            avg_hr = calorie_stats.loc[cat, ('avg_hr', 'mean')]
            min_hr = calorie_stats.loc[cat, ('min_hr', 'mean')]
            dip = calorie_stats.loc[cat, ('dip_rate', 'mean')]
            time_min = calorie_stats.loc[cat, ('time_to_min_hr', 'mean')]
            f.write(f"| {cat} | {count} | {avg_hr:.1f} | {min_hr:.1f} | "
                   f"{dip:.1f} | {time_min:.0f} |\n")
        f.write("\n")

        # タンパク質別
        f.write("### タンパク質摂取量別の心拍数\n\n")
        f.write("| タンパク質区分 | データ数 | 平均心拍数 | 最低心拍数 | ディップ率(%) | 最低HR到達(分) |\n")
        f.write("|----------------|----------|------------|------------|---------------|----------------|\n")

        protein_stats = category_analysis['protein_stats']
        for cat in protein_stats.index:
            count = int(protein_stats.loc[cat, ('avg_hr', 'count')])
            avg_hr = protein_stats.loc[cat, ('avg_hr', 'mean')]
            min_hr = protein_stats.loc[cat, ('min_hr', 'mean')]
            dip = protein_stats.loc[cat, ('dip_rate', 'mean')]
            time_min = protein_stats.loc[cat, ('time_to_min_hr', 'mean')]
            f.write(f"| {cat} | {count} | {avg_hr:.1f} | {min_hr:.1f} | "
                   f"{dip:.1f} | {time_min:.0f} |\n")
        f.write("\n")

        # 考察
        f.write("## 💡 考察と解釈\n\n")
        f.write("### 心拍数指標の意味\n\n")
        f.write("1. **ディップ率が高い** = 良い回復\n")
        f.write("   - 日中から睡眠中の心拍数の低下が大きい\n")
        f.write("   - 副交感神経が優位で、体がリラックスしている\n\n")

        f.write("2. **最低心拍数が低い** = 深いリラクゼーション\n")
        f.write("   - 体が深く休息している状態\n")
        f.write("   - 心臓への負担が少ない\n\n")

        f.write("3. **最低HR到達時間が早い** = 速やかな回復\n")
        f.write("   - 入眠後すぐに体が回復モードに入っている\n")
        f.write("   - 睡眠の質が高い可能性\n\n")

        f.write("### 栄養と心拍数の関係\n\n")
        f.write("- 高カロリー食や高脂肪食は心拍数を上昇させる可能性がある\n")
        f.write("- 炭水化物は副交感神経を活性化し、心拍数を低下させる可能性がある\n")
        f.write("- タンパク質は代謝を上げるため、心拍数に影響する可能性がある\n\n")

        # フッター
        f.write("---\n\n")
        f.write(f"*Generated by analyze_sleep_hr_nutrition.py*\n")

    print(f'✓ レポート生成完了: {report_path}')

    # 詳細データもCSV出力
    csv_path = output_dir / 'hr_nutrition_merged_data.csv'
    df.to_csv(csv_path, index=False)
    print(f'✓ 詳細データ保存: {csv_path}')


def run_analysis(output_dir, days=None):
    """
    心拍数と栄養の分析を実行

    Parameters
    ----------
    output_dir : Path
        出力ディレクトリ
    days : int, optional
        分析対象の日数
    """
    print('='*60)
    print('睡眠中の心拍数と食事の関係分析')
    print('='*60)
    print()

    # 画像出力ディレクトリ
    img_dir = output_dir / 'img'
    img_dir.mkdir(parents=True, exist_ok=True)

    # データ読み込みと結合
    df = load_and_merge_hr_nutrition_data(days=days)

    if len(df) == 0:
        print('エラー: 分析対象データがありません')
        return

    # 相関分析
    corr_analysis = calc_hr_correlation_analysis(df)

    # カテゴリ別分析
    category_analysis = create_hr_category_analysis(df)

    # 可視化
    plot_hr_correlation_heatmap(
        corr_analysis['correlation_matrix'],
        save_path=img_dir / 'hr_correlation_heatmap.png'
    )

    plot_hr_scatter_analysis(
        df,
        save_path=img_dir / 'hr_scatter_analysis.png'
    )

    plot_dip_rate_analysis(
        df,
        save_path=img_dir / 'dip_rate_analysis.png'
    )

    # レポート生成
    generate_markdown_report(output_dir, df, corr_analysis, category_analysis)

    print()
    print('='*60)
    print('分析完了!')
    print('='*60)
    print(f'レポート: {output_dir / "HR_NUTRITION_ANALYSIS.md"}')
    print(f'画像: {img_dir}/')


def main():
    """メイン処理"""
    import argparse

    parser = argparse.ArgumentParser(description='睡眠中の心拍数と食事の関係を分析')
    add_common_report_args(
        parser,
        default_output=BASE_DIR / 'issues/007_sleep_food',
        default_days=None
    )
    args = parser.parse_args()

    # 出力ディレクトリ
    output_dir = Path(args.output) if args.output else BASE_DIR / 'issues/007_sleep_food'
    output_dir.mkdir(parents=True, exist_ok=True)

    run_analysis(output_dir, days=args.days)

    return 0


if __name__ == '__main__':
    exit(main())
