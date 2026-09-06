"""sleep / temperature_skin に足した由来・分母の列（ネットワーク不要）

背景: 2026-09-06、本人の申告（入眠3時）と機器の判定（入眠23:25）が食い違った
とき、CSV だけでは「機器の誤判定」なのか「本人がアプリで直した結果」なのかを
判別できず、生 dataPoint を直接叩く羽目になった。皮膚温も同じで、
nightly_relative の 0.5 が大きいのか小さいのかを決める分母（30日標準偏差）を
API は返しているのに捨てていた。

ここで検査するのは2点だけ:
- 新しい列が API の値をそのまま拾えていること
- **既存 CSV に列が無くても、既存行が消えたり壊れたりしないこと**
  （このリポジトリの失敗は例外を出さない。列追加で過去が飛んでも気づけない）
"""

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.clients import googlehealth_client as api
from lib.clients import googlehealth_daily as ghd
from lib.clients import googlehealth_sleep as ghs
from lib.utils.csv_utils import merge_csv, replace_csv_period

START = dt.date(2026, 9, 5)
END = dt.date(2026, 9, 6)


def make_sleep_point(log_id, start, end, metadata, recording_method):
    return {
        'name': f'users/me/dataTypes/sleep/dataPoints/{log_id}',
        'dataSource': {
            'recordingMethod': recording_method,
            'device': {'displayName': 'Charge 6'},
            'platform': 'FITBIT',
        },
        'sleep': {
            'interval': {
                'startTime': start, 'startUtcOffset': '32400s',
                'endTime': end, 'endUtcOffset': '32400s',
            },
            'summary': {
                'minutesAsleep': '464', 'minutesInSleepPeriod': 603,
                'minutesAwake': '139', 'minutesAfterWakeUp': '8',
                'minutesToFallAsleep': '0', 'stagesSummary': [],
            },
            'metadata': metadata,
            'stages': [], 'shortAwakenings': [],
        },
    }


def sleep_rows_from(monkeypatch, points):
    monkeypatch.setattr(api, '_list_sleep_points', lambda *a, **k: points)
    rows, _ = ghs.fetch_sleep_all(None, START, END)
    return rows


def test_sleep_records_manual_edit(monkeypatch):
    point = make_sleep_point(
        '8962712469254757448',
        '2026-09-05T13:30:00Z', '2026-09-05T23:33:00Z',
        {'stagesStatus': 'SUCCEEDED', 'processed': True,
         'manuallyEdited': True, 'mainSleep': True},
        'MANUAL',
    )
    rows = sleep_rows_from(monkeypatch, [point])

    assert len(rows) == 1
    assert rows[0]['manuallyEdited'] is True
    assert rows[0]['recordingMethod'] == 'MANUAL'


def test_sleep_defaults_to_not_edited(monkeypatch):
    """manuallyEdited が無い夜は False。欠測（空欄）にしない。

    空欄にすると「編集されていない」と「情報が無い」が同じ表現になり、
    この列を足した意味が消える。
    """
    point = make_sleep_point(
        '8158629415678204872',
        '2026-09-04T14:31:00Z', '2026-09-04T22:09:00Z',
        {'stagesStatus': 'SUCCEEDED', 'processed': True, 'mainSleep': True},
        'DERIVED',
    )
    rows = sleep_rows_from(monkeypatch, [point])

    assert rows[0]['manuallyEdited'] is False
    assert rows[0]['recordingMethod'] == 'DERIVED'


def make_temp_points(values):
    """values: [(date_dict, nightly, baseline, stddev)]"""
    points = []
    for date, nightly, baseline, stddev in values:
        payload = {
            'date': date,
            'nightlyTemperatureCelsius': nightly,
            'baselineTemperatureCelsius': baseline,
        }
        if stddev is not None:
            payload['relativeNightlyStddev30dCelsius'] = stddev
        points.append({'dailySleepTemperatureDerivations': payload})
    return points


def test_temperature_skin_keeps_absolute_and_stddev(monkeypatch):
    points = make_temp_points([
        ({'year': 2026, 'month': 9, 'day': 6},
         33.41277683134578, 33.47451361867702, 0.2899874253686545),
    ])
    monkeypatch.setattr(api, 'list_data_points', lambda *a, **k: points)

    rows = ghd.fetch_temperature_skin(None, START, END)

    assert len(rows) == 1
    assert rows[0]['nightly_relative'] == -0.1
    assert rows[0]['nightly_celsius'] == 33.41
    assert rows[0]['relative_stddev_30d'] == 0.29


def test_temperature_skin_tolerates_missing_stddev(monkeypatch):
    """stddev が無くても行を落とさない（分母が無いだけで実測値は生きている）"""
    points = make_temp_points([
        ({'year': 2026, 'month': 9, 'day': 5}, 33.5, 33.4, None),
    ])
    monkeypatch.setattr(api, 'list_data_points', lambda *a, **k: points)

    rows = ghd.fetch_temperature_skin(None, START, END)

    assert len(rows) == 1
    assert rows[0]['relative_stddev_30d'] is None
    assert rows[0]['nightly_celsius'] == 33.5


def test_period_replace_keeps_rows_that_lack_the_new_columns(tmp_path):
    """sleep の経路。列を持たない既存行が消えず、値も壊れない"""
    csv = tmp_path / 'sleep.csv'
    pd.DataFrame([
        {'dateOfSleep': '2026-09-01', 'logId': 8158629415678204872, 'minutesAsleep': 480.0},
        {'dateOfSleep': '2026-09-05', 'logId': 8158629415678204873, 'minutesAsleep': 288.0},
    ]).to_csv(csv, index=False)

    df_new = pd.DataFrame([{
        'dateOfSleep': '2026-09-06', 'logId': 8962712469254757448,
        'minutesAsleep': 464.0, 'manuallyEdited': True, 'recordingMethod': 'MANUAL',
    }])

    merged = replace_csv_period(df_new, csv, 'dateOfSleep', START, END,
                                sort_by=['dateOfSleep'])

    assert sorted(merged.dateOfSleep) == ['2026-09-01', '2026-09-05', '2026-09-06']
    old = merged[merged.dateOfSleep == '2026-09-01'].iloc[0]
    assert old.minutesAsleep == 480.0
    assert pd.isna(old.manuallyEdited)          # 空欄であって False ではない
    assert merged[merged.dateOfSleep == '2026-09-06'].iloc[0].recordingMethod == 'MANUAL'
    # 19桁の logId が float 化して丸められていない
    assert str(merged[merged.dateOfSleep == '2026-09-06'].iloc[0].logId) \
        == '8962712469254757448'


def test_merge_csv_keeps_rows_that_lack_the_new_columns(tmp_path):
    """temperature_skin の経路。列を持たない既存行が消えず、値も壊れない"""
    csv = tmp_path / 'temperature_skin.csv'
    pd.DataFrame([
        {'date': '2026-09-01', 'nightly_relative': 0.5, 'log_type': None},
        {'date': '2026-09-05', 'nightly_relative': 0.0, 'log_type': None},
    ]).to_csv(csv, index=False)

    df_new = pd.DataFrame([{
        'date': '2026-09-06', 'nightly_relative': -0.1, 'log_type': None,
        'nightly_celsius': 33.41, 'relative_stddev_30d': 0.29,
    }]).set_index('date')

    merged = merge_csv(df_new, csv, 'date')

    assert len(merged) == 3
    assert merged.loc[pd.Timestamp('2026-09-01'), 'nightly_relative'] == 0.5
    assert pd.isna(merged.loc[pd.Timestamp('2026-09-01'), 'nightly_celsius'])
    assert merged.loc[pd.Timestamp('2026-09-06'), 'relative_stddev_30d'] == 0.29
