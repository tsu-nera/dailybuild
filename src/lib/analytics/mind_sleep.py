#!/usr/bin/env python
# coding: utf-8
"""
メンタルレポート用 睡眠パターンデータ準備

mind.py から分離したモジュール。
"""

import pandas as pd


def prepare_sleep_patterns_daily_data(start_date, end_date, df_sleep, df_levels=None):
    """
    睡眠パターンの日別データを準備

    Args:
        start_date: 開始日
        end_date: 終了日
        df_sleep: 睡眠データフレーム（dateOfSleep列あり）
        df_levels: 睡眠レベルデータフレーム（sleep_levels.csv、オプショナル）

    Returns:
        list[dict]: 日別データリスト（入眠潜時・起床後時間含む）
    """
    from lib.analytics.sleep import calc_sleep_timing

    sleep_data = []
    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')

    # 入眠潜時・起床後時間を計算（df_levelsが提供されている場合）
    sleep_timing = {}
    if df_levels is not None and not df_levels.empty:
        raw_timing = calc_sleep_timing(df_levels)
        # キーを日付文字列('YYYY-MM-DD')に正規化（calc_sleep_timingはdatetime型キーを返す場合がある）
        for key, value in raw_timing.items():
            date_key = pd.to_datetime(key).strftime('%Y-%m-%d')
            sleep_timing[date_key] = value

    for date in all_dates:
        row = {'date': date}
        date_str = date.strftime('%Y-%m-%d')

        # 睡眠データ
        if df_sleep is not None:
            sleep_day = df_sleep[df_sleep['dateOfSleep'] == date]
            if len(sleep_day) > 0:
                # 就寝時刻
                if 'startTime' in sleep_day.columns:
                    start_time = sleep_day.iloc[0]['startTime']
                    if pd.notna(start_time):
                        row['bedtime'] = pd.to_datetime(start_time).strftime('%H:%M')
                    else:
                        row['bedtime'] = None
                else:
                    row['bedtime'] = None

                # 起床時刻
                if 'endTime' in sleep_day.columns:
                    end_time = sleep_day.iloc[0]['endTime']
                    if pd.notna(end_time):
                        row['waketime'] = pd.to_datetime(end_time).strftime('%H:%M')
                    else:
                        row['waketime'] = None
                else:
                    row['waketime'] = None

                # 睡眠時間
                val = sleep_day.iloc[0]['minutesAsleep']
                row['sleep_hours'] = float(val) / 60 if pd.notna(val) else None

                # 効率
                val = sleep_day.iloc[0]['efficiency']
                row['efficiency'] = float(val) if pd.notna(val) else None

                # 覚醒時間（分）
                if 'minutesAwake' in sleep_day.columns:
                    val = sleep_day.iloc[0]['minutesAwake']
                    row['minutes_awake'] = float(val) if pd.notna(val) else None
                else:
                    row['minutes_awake'] = None

                # 中途覚醒回数
                if 'wakeCount' in sleep_day.columns:
                    val = sleep_day.iloc[0]['wakeCount']
                    row['wake_count'] = int(val) if pd.notna(val) else None
                else:
                    row['wake_count'] = None
            else:
                row['bedtime'] = None
                row['waketime'] = None
                row['sleep_hours'] = None
                row['efficiency'] = None
                row['minutes_awake'] = None
                row['wake_count'] = None
        else:
            row['bedtime'] = None
            row['waketime'] = None
            row['sleep_hours'] = None
            row['efficiency'] = None
            row['minutes_awake'] = None
            row['wake_count'] = None

        # 入眠潜時・起床後時間（sleep_timingから取得）
        if date_str in sleep_timing:
            timing = sleep_timing[date_str]
            row['minutes_to_fall_asleep'] = timing.get('minutes_to_fall_asleep')
            row['minutes_after_wakeup'] = timing.get('minutes_after_wakeup')
        else:
            row['minutes_to_fall_asleep'] = None
            row['minutes_after_wakeup'] = None

        sleep_data.append(row)

    return sleep_data
