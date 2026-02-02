#!/usr/bin/env python
# coding: utf-8
"""
食事と睡眠の関係を分析するスクリプト

既存の睡眠分析ライブラリを活用して、栄養データとの相関を分析します。

Usage:
    python scripts/analyze_sleep_nutrition.py [--output <DIR>] [--days <N>]
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
from lib.utils.report_args import add_common_report_args, parse_period_args

# データファイルパス
BASE_DIR = project_root
SLEEP_CSV = BASE_DIR / 'data/fitbit/sleep.csv'
NUTRITION_CSV = BASE_DIR / 'data/fitbit/nutrition.csv'


def load_and_merge_data(days=None):
    """
    睡眠データと栄養データを読み込んで結合

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

    # 栄養データがある日のみ抽出（calories > 0）
    df_nutrition = df_nutrition[df_nutrition['calories'] > 0].copy()

    # 日数でフィルタリング
    if days is not None:
        end_date = df_sleep['dateOfSleep'].max()
        start_date = end_date - pd.Timedelta(days=days)
        df_sleep = df_sleep[df_sleep['dateOfSleep'] >= start_date]
        df_nutrition = df_nutrition[df_nutrition['date'] >= start_date]

    print(f'  睡眠データ: {len(df_sleep)}日分')
    print(f'  栄養データ: {len(df_nutrition)}日分（記録あり）')

    # データ結合: 栄養データの翌日の睡眠と紐付け
    merged_list = []
    for _, nutr_row in df_nutrition.iterrows():
        nutrition_date = nutr_row['date']
        sleep_date = nutrition_date + pd.Timedelta(days=1)

        # 対応する睡眠データを検索
        sleep_rows = df_sleep[df_sleep['dateOfSleep'] == sleep_date]
        if len(sleep_rows) > 0:
            sleep_row = sleep_rows.iloc[0]
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
                # 睡眠指標
                'sleep_minutes': sleep_row['minutesAsleep'],
                'sleep_efficiency': sleep_row['efficiency'],
                'minutes_awake': sleep_row['minutesAwake'],
                'deep_minutes': sleep_row['deepMinutes'],
                'light_minutes': sleep_row['lightMinutes'],
                'rem_minutes': sleep_row['remMinutes'],
                'wake_minutes': sleep_row['wakeMinutes'],
            })

    df_merged = pd.DataFrame(merged_list)
    print(f'  結合データ: {len(df_merged)}日分')

    return df_merged


def calc_correlation_analysis(df):
    """
    相関分析を実施

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

    # 相関係数計算
    nutrients = ['calories', 'carbs', 'fat', 'fiber', 'protein', 'sodium']
    sleep_metrics = ['sleep_minutes', 'sleep_efficiency', 'minutes_awake',
                     'deep_minutes', 'light_minutes', 'rem_minutes']

    corr = df[nutrients + sleep_metrics].corr()

    # 栄養素と睡眠指標の相関を抽出
    sleep_nutrition_corr = corr.loc[sleep_metrics, nutrients]

    # 最も相関の強い組み合わせを抽出
    abs_corr = sleep_nutrition_corr.abs()
    max_correlations = {}
    for metric in sleep_metrics:
        max_nutrient = abs_corr.loc[metric].idxmax()
        max_correlations[metric] = {
            'nutrient': max_nutrient,
            'value': corr.loc[metric, max_nutrient]
        }

    return {
        'correlation_matrix': sleep_nutrition_corr,
        'max_correlations': max_correlations
    }


def create_category_analysis(df):
    """
    カテゴリ別分析

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
        ['sleep_minutes', 'sleep_efficiency', 'deep_minutes', 'rem_minutes']
    ].agg(['mean', 'count'])

    # タンパク質区分
    df['protein_category'] = pd.cut(df['protein'],
                                      bins=[0, 50, 80, 120, 200],
                                      labels=['低(~50g)', '中(50-80g)',
                                             '高(80-120g)', '過多(120g~)'])

    protein_stats = df.groupby('protein_category', observed=True)[
        ['sleep_minutes', 'sleep_efficiency', 'deep_minutes', 'rem_minutes']
    ].agg(['mean', 'count'])

    return {
        'calorie_stats': calorie_stats,
        'protein_stats': protein_stats
    }


def plot_correlation_heatmap(corr_matrix, save_path):
    """
    相関係数のヒートマップを作成

    Parameters
    ----------
    corr_matrix : pd.DataFrame
        相関係数行列
    save_path : Path
        保存先パス
    """
    print('プロット中: 相関ヒートマップ...')

    plt.figure(figsize=(10, 6))
    sns.heatmap(corr_matrix, annot=True, fmt='.3f', cmap='coolwarm',
                center=0, vmin=-1, vmax=1, cbar_kws={'label': '相関係数'})
    plt.title('栄養素と睡眠指標の相関係数', fontsize=14, pad=20)
    plt.xlabel('栄養素', fontsize=12)
    plt.ylabel('睡眠指標', fontsize=12)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()


def plot_scatter_analysis(df, save_path):
    """
    散布図による関係性の可視化

    Parameters
    ----------
    df : pd.DataFrame
        結合データ
    save_path : Path
        保存先パス
    """
    print('プロット中: 散布図...')

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle('栄養素と睡眠時間の関係', fontsize=14)

    nutrients = ['calories', 'carbs', 'fat', 'fiber', 'protein', 'sodium']
    for i, nutrient in enumerate(nutrients):
        ax = axes[i // 3, i % 3]
        ax.scatter(df[nutrient], df['sleep_minutes'], alpha=0.6)

        # 回帰直線
        z = np.polyfit(df[nutrient], df['sleep_minutes'], 1)
        p = np.poly1d(z)
        ax.plot(df[nutrient], p(df[nutrient]), "r--", alpha=0.8)

        # 相関係数を表示
        corr = df[[nutrient, 'sleep_minutes']].corr().iloc[0, 1]
        ax.set_title(f'{nutrient} (r={corr:.3f})')
        ax.set_xlabel(nutrient)
        ax.set_ylabel('睡眠時間(分)')
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()


def generate_markdown_report(output_dir, df, corr_analysis, category_analysis):
    """
    Markdownレポートを生成

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

    report_path = output_dir / 'ANALYSIS.md'

    with open(report_path, 'w', encoding='utf-8') as f:
        # ヘッダー
        f.write("# 食事と睡眠の関係分析レポート\n\n")
        f.write(f"**生成日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("---\n\n")

        # データサマリー
        f.write("## 📊 データサマリー\n\n")
        f.write(f"- **分析対象**: {len(df)}日分のデータ\n")
        f.write(f"- **期間**: {df['nutrition_date'].min().strftime('%Y-%m-%d')} ~ "
                f"{df['nutrition_date'].max().strftime('%Y-%m-%d')}\n")
        f.write("- **分析内容**: 食事記録の翌日の睡眠データとの相関分析\n\n")

        # 栄養素の基本統計
        f.write("## 🍽️ 栄養素の基本統計\n\n")
        f.write("| 指標 | カロリー(kcal) | 炭水化物(g) | 脂質(g) | 食物繊維(g) | タンパク質(g) | 塩分(mg) |\n")
        f.write("|------|----------------|-------------|---------|-------------|---------------|----------|\n")

        stats_rows = {
            '平均': lambda col: f"{df[col].mean():.1f}",
            '中央値': lambda col: f"{df[col].median():.1f}",
            '最小': lambda col: f"{df[col].min():.1f}",
            '最大': lambda col: f"{df[col].max():.1f}",
        }

        nutrients = ['calories', 'carbs', 'fat', 'fiber', 'protein', 'sodium']
        for label, func in stats_rows.items():
            f.write(f"| {label} | ")
            f.write(" | ".join([func(n) for n in nutrients]))
            f.write(" |\n")
        f.write("\n")

        # 睡眠の基本統計
        f.write("## 😴 睡眠の基本統計\n\n")
        f.write("| 指標 | 睡眠時間(分) | 睡眠効率(%) | 深い睡眠(分) | REM睡眠(分) |\n")
        f.write("|------|--------------|-------------|--------------|-------------|\n")

        sleep_cols = ['sleep_minutes', 'sleep_efficiency', 'deep_minutes', 'rem_minutes']
        for label, func in stats_rows.items():
            f.write(f"| {label} | ")
            values = []
            for col in sleep_cols:
                val = func(col)
                if col == 'sleep_minutes':
                    hours = df[col].mean() / 60 if label == '平均' else df[col].median() / 60
                    val = f"{val} ({hours:.1f}h)"
                values.append(val)
            f.write(" | ".join(values))
            f.write(" |\n")
        f.write("\n")

        # 相関分析
        f.write("## 🔗 栄養素と睡眠の相関分析\n\n")
        f.write("### 相関係数マトリックス\n\n")
        f.write("相関係数は-1~1の範囲。**絶対値が0.3以上**で中程度、**0.5以上**で強い相関を示します。\n\n")

        corr_matrix = corr_analysis['correlation_matrix']

        # テーブルヘッダー
        f.write("| 睡眠指標 | ")
        f.write(" | ".join(nutrients))
        f.write(" |\n")
        f.write("|" + "---|" * (len(nutrients) + 1) + "\n")

        # 相関係数テーブル
        sleep_metric_names = {
            'sleep_minutes': '睡眠時間',
            'sleep_efficiency': '睡眠効率',
            'minutes_awake': '覚醒時間',
            'deep_minutes': '深い睡眠',
            'light_minutes': '浅い睡眠',
            'rem_minutes': 'REM睡眠'
        }

        for metric in corr_matrix.index:
            f.write(f"| {sleep_metric_names.get(metric, metric)} |")
            for nutrient in corr_matrix.columns:
                val = corr_matrix.loc[metric, nutrient]
                # 強い相関は太字
                if abs(val) >= 0.3:
                    f.write(f" **{val:.3f}** |")
                else:
                    f.write(f" {val:.3f} |")
            f.write("\n")
        f.write("\n")

        # ヒートマップ画像
        f.write("### 相関ヒートマップ\n\n")
        f.write("![相関ヒートマップ](img/correlation_heatmap.png)\n\n")

        # 最も相関の強い組み合わせ
        f.write("### 📈 主な発見\n\n")
        max_corrs = corr_analysis['max_correlations']
        for metric, data in max_corrs.items():
            metric_name = sleep_metric_names.get(metric, metric)
            nutrient = data['nutrient']
            value = data['value']
            direction = "正の相関" if value > 0 else "負の相関"
            strength = "強い" if abs(value) >= 0.5 else "中程度の" if abs(value) >= 0.3 else "弱い"

            f.write(f"- **{metric_name}**: {nutrient}と{strength}{direction} (r={value:.3f})\n")
        f.write("\n")

        # 散布図
        f.write("### 散布図分析\n\n")
        f.write("![散布図](img/scatter_analysis.png)\n\n")

        # カテゴリ別分析
        f.write("## 📊 カテゴリ別分析\n\n")

        # カロリー別
        f.write("### カロリー摂取量別の睡眠\n\n")
        f.write("| カロリー区分 | データ数 | 平均睡眠時間 | 睡眠効率(%) | 深い睡眠(分) | REM睡眠(分) |\n")
        f.write("|--------------|----------|--------------|-------------|--------------|-------------|\n")

        calorie_stats = category_analysis['calorie_stats']
        for cat in calorie_stats.index:
            count = int(calorie_stats.loc[cat, ('sleep_minutes', 'count')])
            sleep_min = calorie_stats.loc[cat, ('sleep_minutes', 'mean')]
            efficiency = calorie_stats.loc[cat, ('sleep_efficiency', 'mean')]
            deep = calorie_stats.loc[cat, ('deep_minutes', 'mean')]
            rem = calorie_stats.loc[cat, ('rem_minutes', 'mean')]
            f.write(f"| {cat} | {count} | {sleep_min:.0f}分 ({sleep_min/60:.1f}h) | "
                   f"{efficiency:.1f} | {deep:.0f} | {rem:.0f} |\n")
        f.write("\n")

        # タンパク質別
        f.write("### タンパク質摂取量別の睡眠\n\n")
        f.write("| タンパク質区分 | データ数 | 平均睡眠時間 | 睡眠効率(%) | 深い睡眠(分) | REM睡眠(分) |\n")
        f.write("|----------------|----------|--------------|-------------|--------------|-------------|\n")

        protein_stats = category_analysis['protein_stats']
        for cat in protein_stats.index:
            count = int(protein_stats.loc[cat, ('sleep_minutes', 'count')])
            sleep_min = protein_stats.loc[cat, ('sleep_minutes', 'mean')]
            efficiency = protein_stats.loc[cat, ('sleep_efficiency', 'mean')]
            deep = protein_stats.loc[cat, ('deep_minutes', 'mean')]
            rem = protein_stats.loc[cat, ('rem_minutes', 'mean')]
            f.write(f"| {cat} | {count} | {sleep_min:.0f}分 ({sleep_min/60:.1f}h) | "
                   f"{efficiency:.1f} | {deep:.0f} | {rem:.0f} |\n")
        f.write("\n")

        # 考察
        f.write("## 💡 考察と次のステップ\n\n")
        f.write("### 相関から見た傾向\n\n")

        # 睡眠時間との相関
        sleep_min_corr = corr_analysis['max_correlations']['sleep_minutes']
        f.write(f"1. **睡眠時間**: {sleep_min_corr['nutrient']}との相関が最も強い "
               f"(r={sleep_min_corr['value']:.3f})\n")

        # 睡眠効率との相関
        efficiency_corr = corr_analysis['max_correlations']['sleep_efficiency']
        f.write(f"2. **睡眠効率**: {efficiency_corr['nutrient']}との相関が最も強い "
               f"(r={efficiency_corr['value']:.3f})\n")

        # 深い睡眠との相関
        deep_corr = corr_analysis['max_correlations']['deep_minutes']
        f.write(f"3. **深い睡眠**: {deep_corr['nutrient']}との相関が最も強い "
               f"(r={deep_corr['value']:.3f})\n\n")

        f.write("### 今後の分析案\n\n")
        f.write("1. **時系列分析**: 栄養摂取パターンと睡眠の長期トレンド\n")
        f.write("2. **PFCバランス分析**: タンパク質・脂質・炭水化物の比率と睡眠の関係\n")
        f.write("3. **多変量解析**: 複数の栄養素を組み合わせた睡眠予測モデル\n")
        f.write("4. **外れ値分析**: 特に睡眠が良好/不良だった日の栄養パターン\n")
        f.write("5. **食事タイミング**: 夕食時刻と睡眠開始時刻の関係(データ追加が必要)\n\n")

        # フッター
        f.write("---\n\n")
        f.write(f"*Generated by analyze_sleep_nutrition.py*\n")

    print(f'✓ レポート生成完了: {report_path}')

    # 詳細データもCSV出力
    csv_path = output_dir / 'merged_data.csv'
    df.to_csv(csv_path, index=False)
    print(f'✓ 詳細データ保存: {csv_path}')


def run_analysis(output_dir, days=None):
    """
    分析を実行

    Parameters
    ----------
    output_dir : Path
        出力ディレクトリ
    days : int, optional
        分析対象の日数
    """
    print('='*60)
    print('食事と睡眠の関係分析')
    print('='*60)
    print()

    # 画像出力ディレクトリ
    img_dir = output_dir / 'img'
    img_dir.mkdir(parents=True, exist_ok=True)

    # データ読み込みと結合
    df = load_and_merge_data(days=days)

    if len(df) == 0:
        print('エラー: 分析対象データがありません')
        return

    # 相関分析
    corr_analysis = calc_correlation_analysis(df)

    # カテゴリ別分析
    category_analysis = create_category_analysis(df)

    # 可視化
    plot_correlation_heatmap(
        corr_analysis['correlation_matrix'],
        save_path=img_dir / 'correlation_heatmap.png'
    )

    plot_scatter_analysis(
        df,
        save_path=img_dir / 'scatter_analysis.png'
    )

    # レポート生成
    generate_markdown_report(output_dir, df, corr_analysis, category_analysis)

    print()
    print('='*60)
    print('分析完了!')
    print('='*60)
    print(f'レポート: {output_dir / "ANALYSIS.md"}')
    print(f'画像: {img_dir}/')


def main():
    """メイン処理"""
    import argparse

    parser = argparse.ArgumentParser(description='食事と睡眠の関係を分析')
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
