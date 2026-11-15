#!/usr/bin/env python
# coding: utf-8
"""
ワークアウトデータ分析ライブラリ

`scripts/hevy.py show` と `scripts/dashboard.py` が使う週次集計（部位別セット数 / 種目別 e1RM / 腹囲 /
頻度・時間・ボリューム・レップ）を提供。
"""

from pathlib import Path

import pandas as pd
import yaml

EXERCISE_MUSCLES_YAML = Path(__file__).resolve().parents[3] / 'config' / 'exercise_muscles.yaml'

# 部位コード → 表示名。Hevy アプリの6部位と同じ並び。yaml に無い値が来たらコードのままフォールバックする
MUSCLE_LABELS = {
    'back': '背中',
    'chest': '胸',
    'core': '体幹',
    'shoulders': '肩',
    'arms': '腕',
    'legs': '脚',
}


def load_muscle_mapping(yaml_path=EXERCISE_MUSCLES_YAML):
    """種目名（正規化後） → 部位コード のマッピングを yaml から読み込む"""
    with Path(yaml_path).open(encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    exercises = data.get('exercises') or {}
    return {name: info['muscle'] for name, info in exercises.items()}


def load_weekly_set_targets(yaml_path=EXERCISE_MUSCLES_YAML):
    """部位コード → 週あたり目標セット数 のマッピングを yaml から読み込む

    Parameters
    ----------
    yaml_path : Path
        `config/exercise_muscles.yaml` へのパス

    Returns
    -------
    dict
        部位コード → target（int）。yaml に `weekly_sets` が無い/空なら空 dict。
        `since` は読むだけで返り値には含めない
    """
    with Path(yaml_path).open(encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    weekly_sets = data.get('weekly_sets') or {}
    return {muscle: int(info['target']) for muscle, info in weekly_sets.items()}


def weekly_set_progress(sets_table, week_label, targets):
    """
    指定週の部位別セット数を目標と突き合わせ、実績・目標・残量を返す

    Parameters
    ----------
    sets_table : DataFrame
        weekly_muscle_sets() の第1戻り値（index=週ラベル、columns=部位コード）
    week_label : str
        対象週のラベル（`YYYY-Wxx`）
    targets : dict
        load_weekly_set_targets() の戻り値（部位コード → 目標セット数）

    Returns
    -------
    list[dict]
        `targets` の順に、部位ごとの
        {'muscle', 'label', 'actual', 'target', 'remaining'} を並べたもの。
        `targets` に無い部位は含めない。`sets_table` に列が無い、または
        `week_label` が index に無い場合 actual は 0 とする
    """
    rows = []
    for muscle, target in targets.items():
        actual = 0
        if muscle in sets_table.columns and week_label in sets_table.index:
            actual = int(sets_table.loc[week_label, muscle])
        rows.append({
            'muscle': muscle,
            'label': MUSCLE_LABELS.get(muscle, muscle),
            'actual': actual,
            'target': target,
            'remaining': max(target - actual, 0),
        })
    return rows


def weekly_set_status(df_workouts, week_label, session_dates, muscle_map, targets):
    """
    指定週の部位別セット数の残量と、Hevy export 未反映の疑いがある日を返す

    body レポートと STATE.md（journal_skeleton.py）が共有する。片方だけ直すと
    同じ週について2つのセット数が出る。

    Parameters
    ----------
    df_workouts : DataFrame
        hevy_csv.parse_hevy_csv() の戻り値
    week_label : str
        対象週のラベル（`YYYY-Wxx`）
    session_dates : iterable of datetime.date
        exercise_source の筋トレセッションがあった日。export 未反映の検出に使う
    muscle_map : dict
        load_muscle_mapping() の戻り値
    targets : dict
        load_weekly_set_targets() の戻り値

    Returns
    -------
    dict
        {'week_label', 'rows', 'missing_export_dates'}。missing_export_dates は
        今週のうち、筋トレセッションがあるのに workouts.csv に同日のセットが1件も
        無い日（`YYYY-MM-DD`）。あればセット数は過少の可能性がある
    """
    sets_table, _unmapped = weekly_muscle_sets(df_workouts, muscle_map, [week_label])
    rows = weekly_set_progress(sets_table, week_label, targets)

    year_str, week_str = week_label.split('-W')
    monday = pd.Timestamp.fromisocalendar(int(year_str), int(week_str), 1).date()
    week_dates = {monday + pd.Timedelta(days=i) for i in range(7)}
    hevy_dates = set(pd.to_datetime(df_workouts['start_dt']).dt.date) & week_dates
    missing = sorted(d.strftime('%Y-%m-%d')
                     for d in (set(session_dates) & week_dates) - hevy_dates)

    return {'week_label': week_label, 'rows': rows, 'missing_export_dates': missing}


def add_week_label(df, date_column='start_dt'):
    """ISO週ラベル（`YYYY-Wxx`）の列 week_label を追加する"""
    df = df.copy()
    iso = df[date_column].dt.isocalendar()
    df['week_label'] = iso['year'].astype(str) + '-W' + iso['week'].astype(int).map('{:02d}'.format)
    return df


def recent_iso_weeks(n, today=None):
    """直近 n 週の ISO週ラベルを古い→新しいの順で返す（今週を含む）

    記録の無い週も表に出すため、データではなく暦から週の一覧を作る。
    """
    today = pd.Timestamp(today) if today is not None else pd.Timestamp.now().normalize()
    iso_today = today.isocalendar()
    monday_this_week = today - pd.Timedelta(days=int(iso_today.weekday) - 1)

    labels = []
    for i in range(n - 1, -1, -1):
        monday = monday_this_week - pd.Timedelta(days=7 * i)
        iso = monday.isocalendar()
        labels.append(f'{iso.year}-W{iso.week:02d}')
    return labels


def weekly_muscle_sets(df, muscle_map, week_labels):
    """
    週 × 部位のセット数、トレーニング日数、未マッピング種目を集計する

    Parameters
    ----------
    df : DataFrame
        parse_hevy_csv() 済みの DataFrame（start_dt, exercise_title を含む）
    muscle_map : dict
        exercise_title（正規化後） → 部位コード
    week_labels : list[str]
        表に出す週（古い→新しい）。この範囲外のセットは無視する

    Returns
    -------
    (sets_table, unmapped)
        sets_table : DataFrame
            index=week_labels、columns=部位コード（アルファベット順）+ 'training_days'。
            記録が1セットも無い週も 0 の行として含む
        unmapped : DataFrame
            columns=['exercise_title', 'sets']。yaml に無い種目とそのセット数
            （セット数降順）。無ければ空の DataFrame
    """
    df = add_week_label(df)
    df = df[df['week_label'].isin(week_labels)].copy()

    if df.empty:
        training_days = pd.Series(0, index=week_labels, dtype=int)
    else:
        training_days = (
            df.groupby('week_label')['start_dt']
            .apply(lambda s: s.dt.date.nunique())
            .reindex(week_labels, fill_value=0)
            .astype(int)
        )

    df['muscle'] = df['exercise_title'].map(muscle_map)
    unmapped_mask = df['muscle'].isna()

    unmapped = (
        df.loc[unmapped_mask]
        .groupby('exercise_title')
        .size()
        .reset_index(name='sets')
        .sort_values('sets', ascending=False)
        .reset_index(drop=True)
    )

    mapped = df.loc[~unmapped_mask]
    if mapped.empty:
        sets_table = pd.DataFrame(index=week_labels)
    else:
        sets_table = (
            mapped.groupby(['week_label', 'muscle'])
            .size()
            .unstack(fill_value=0)
        )
        sets_table = sets_table.reindex(week_labels, fill_value=0)
        sets_table = sets_table.reindex(columns=sorted(sets_table.columns), fill_value=0)

    sets_table['training_days'] = training_days

    return sets_table, unmapped


def calc_e1rm(weight_kg, reps):
    """Epley 式で 1レップ最大重量を推定する（自重は呼び出し側で除外する）"""
    return weight_kg * (1 + reps / 30)


def weekly_e1rm(df, week_labels):
    """
    種目別 e1RM の週次推移（その週の最大値）を計算する

    `weight_kg` が空（自重）のセットは計算から除外する。窓の中で1度も
    実施していない種目は結果に含めない（列が全て NaN になるので呼び出し側で
    dropna(axis=1, how='all') する想定）。

    Parameters
    ----------
    df : DataFrame
        parse_hevy_csv() 済みの DataFrame
    week_labels : list[str]
        表に出す週（古い→新しい）

    Returns
    -------
    DataFrame
        index=week_labels、columns=exercise_title。未実施セルは NaN
    """
    df = df[df['weight_kg'].notna()].copy()
    if df.empty:
        return pd.DataFrame(index=week_labels)

    df['e1rm'] = calc_e1rm(df['weight_kg'], df['reps'])
    df = add_week_label(df)
    df = df[df['week_label'].isin(week_labels)]

    if df.empty:
        return pd.DataFrame(index=week_labels)

    pivot = df.groupby(['week_label', 'exercise_title'])['e1rm'].max().unstack()
    pivot = pivot.reindex(week_labels)
    pivot = pivot.sort_index(axis=1)
    return pivot


def weekly_waist(measurements_df, week_labels):
    """
    腹囲（waist_cm）の週次推移。測定の無い週は NaN のままにし、前週の値で埋めない。
    同じ週に複数の測定があれば日付が最も新しいものを採る。

    Parameters
    ----------
    measurements_df : DataFrame
        parse_hevy_measurements() 済みの DataFrame（date, waist_cm を含む）
    week_labels : list[str]
        表に出す週（古い→新しい）

    Returns
    -------
    Series
        index=week_labels、値は waist_cm（float、未測定週は NaN）
    """
    df = measurements_df.dropna(subset=['waist_cm']).copy()
    if df.empty:
        return pd.Series(index=week_labels, dtype=float, name='waist_cm')

    df['date'] = pd.to_datetime(df['date'])
    df = add_week_label(df, date_column='date')
    df = df.sort_values('date')
    weekly = df.groupby('week_label')['waist_cm'].last()
    return weekly.reindex(week_labels)


def weeks_since(first_date, today):
    """first_date の週から today の週までの ISO週ラベル（古い→新しい）"""
    first = pd.Timestamp(first_date).normalize()
    today = pd.Timestamp(today).normalize()
    weeks = (today - pd.Timedelta(days=today.weekday()) - (first - pd.Timedelta(days=first.weekday()))).days // 7 + 1
    return recent_iso_weeks(max(weeks, 1), today)


def weekly_training_stats(df, week_labels):
    """
    週ごとの時間・ボリューム・レップ・セット（頻度は weekly_muscle_sets() の training_days）

    - minutes: ワークアウトの開始〜終了の合計（同じワークアウトの行は1回だけ数える）
    - volume_kg: 重量 × 回数の合計。**重量のあるセットだけ**（自重は回数を重量の代わりに
      足すと壊れるので含めない）
    - reps: 回数の合計（自重を含む）
    - sets: セット数（自重を含む。部位別セット数と同じ数え方）

    記録の無い週は 0 の行にする。

    Parameters
    ----------
    df : DataFrame
        parse_hevy_csv() 済みの DataFrame
    week_labels : list[str]
        表に出す週（古い→新しい）

    Returns
    -------
    DataFrame
        index=week_labels、columns=['minutes', 'volume_kg', 'reps', 'sets']
    """
    cols = ['minutes', 'volume_kg', 'reps', 'sets']
    df = add_week_label(df)
    df = df[df['week_label'].isin(week_labels)].copy()
    if df.empty:
        return pd.DataFrame(0, index=week_labels, columns=cols)

    df['volume'] = (df['weight_kg'] * df['reps']).where(df['weight_kg'].notna(), 0)
    workouts = df.drop_duplicates(['start_dt', 'end_dt']).copy()
    workouts['minutes'] = (workouts['end_dt'] - workouts['start_dt']).dt.total_seconds() / 60

    by_week = df.groupby('week_label')
    out = pd.DataFrame({
        'minutes': workouts.groupby('week_label')['minutes'].sum().round(),
        'volume_kg': by_week['volume'].sum().round(),
        'reps': by_week['reps'].sum(),
        'sets': by_week.size(),
    })
    return out.reindex(week_labels, fill_value=0)[cols].astype(int)
