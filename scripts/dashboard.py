#!/usr/bin/env python3
"""
週の目標ダッシュボード（claude.ai の Artifact）に載せる数値を JSON に書き出す

ページ（scripts/dashboard/index.html）は数値を持たない。数値はこの JSON 1本で、
Artifact へは agent が添付ファイルとして上げ直す（スクリプトからは公開できない）。
目標値は config/targets.yaml（睡眠）と config/exercise_muscles.yaml の weekly_sets（筋トレ）
から読むので、目標を書き換えればダッシュボードも追随する。

同じ数値を Grafana 用の CSV 7本（nights / weeks / sets / status / current / sets_now /
freshness）としても reports/dashboard/ へ全上書きで書く（docs/grafana.md）。欠測は空セル。
加えて body / sleep / mind 画面用の daily.csv（直近 DAILY_DAYS 日、1日1行）と、
消耗品画面用の consumables.csv / consumable_purchases.csv（lib/consumables.py）、
お金の画面用の assets.csv / assets_now.csv / goods.csv（lib/assets.py）と balances_daily.csv / balances_now.csv（lib/balances.py）、
瞑想の画面用の meditation_{daily,weeks,now,muse,eval}.csv（lib/meditation.py。muse・eval は satoru の session_log）、
老化の画面用の longevity_{catalog,monthly,labs}.csv（lib/longevity.py。台帳は config/longevity.yaml）を書く。
計算はここに1本で、Grafana 側では集計も判定もしない。習慣の行（goals_list）の日数だけは
lib/habits/weekly.py が数え、ここでは並べるだけ（数え方を habits_daily.csv に1本化するため）。

Usage:
    uv run scripts/dashboard.py build [--only goals,daily,consumables,assets,balances,meditation,strength,longevity] [--weeks 8]
                                      [--out tmp/dashboard/goals.json] [--csv-dir reports/dashboard]
        --only を省くと全グループ。指定したグループの CSV だけ作り直す（台帳を書いた直後・相場を引いた
        直後に Grafana へ反映する用。全体は約10秒）。--out の JSON は goals を作ったときだけ書く
"""

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib import assets, balances, consumables, exercise_source, hevy_csv, longevity, meditation  # noqa: E402
from lib.analytics import activity, body  # noqa: E402
from lib.analytics import workout  # noqa: E402
from lib.habits import config as habits_config  # noqa: E402
from lib.habits import weekly as habits_weekly  # noqa: E402
from lib.toggl import focus as toggl_focus  # noqa: E402
from lib.analytics.sleep.nightly import (  # noqa: E402
    SLEEP_PER_NIGHT_H, build_nights, debt_by_day, main_sleep, week_label)
from lib.utils.private_data import ensure_dir, require_private_path, require_private_write  # noqa: E402
from lib.utils.targets import get_target  # noqa: E402
from journal_skeleton import collect_daily_detail, collect_pipeline  # noqa: E402

SLEEP_CSV = project_root / 'data/wearable/sleep.csv'
STEPS_CSV = project_root / 'data/wearable/steps_intraday.csv'
WORKOUTS_CSV = project_root / 'data/hevy/workouts.csv'
INNERSCAN_CSV = project_root / 'data/healthplanet_innerscan.csv'
SPO2_CSV = project_root / 'data/wearable/spo2.csv'
NUTRITION_CSV = project_root / 'data/wearable/nutrition.csv'
EXERCISE_CSV = project_root / 'data/googlehealth/exercise.csv'
CSV_DIR = project_root / 'reports/dashboard'
TOGGL_FOCUS_CSV = project_root / 'data/toggl/focus_entries.csv'
METRICS_DAILY_CSV = project_root / 'reports/metrics_daily.csv'  # journal_skeleton.py が日次で全上書き
SATORU_SESSION_LOG = meditation.SATORU_SESSION_LOG
CONSUMABLES_CSV = project_root / 'data/inventory/consumables.csv'
PURCHASE_RULES_CSV = project_root / 'data/inventory/purchase_rules.csv'
STOCKTAKE_CSV = project_root / 'data/inventory/stocktake.csv'
MF_ASSETS_CSV = project_root / 'data/mf/資産推移.csv'
MF_BALANCES_CSV = project_root / 'data/mf/balances.csv'
ITEMS_CSV = project_root / 'data/inventory/items.csv'
MARKET_CSV = project_root / 'data/inventory/market.csv'
PURCHASE_CSVS = {'amazon': project_root / 'data/purchases/amazon.csv',
                 'myprotein': project_root / 'data/purchases/myprotein.csv',
                 'rakuten': project_root / 'data/purchases/rakuten.csv',
                 'store': project_root / 'data/purchases/store.csv'}

# daily.csv の期間。推移は Grafana の時間範囲で絞るので、表は長めに持つ
DAILY_DAYS = 365

# Hevy の日時はタイムゾーンを持たない端末の時刻（日本で記録している）
JST = "Asia/Tokyo"

_WEEK_COLS = ['week', 'days', 'nights', 'total_h', 'goal_h', 'avg_h', 'bed_hit', 'bed_n',
              'rise_hit', 'rise_n', 'debt_end_h']
# axis_max は Grafana の縦軸の上限。目標の点線が実績より上にあっても軸の外に出ないようにする
_SET_COLS = ['week', 'muscle', 'sets', 'target', 'remaining', 'axis_max']
# CSV の列順（Grafana 側は列名で選ぶ）
COLUMNS = {
    'status': ['generated_at', 'today', 'this_week', 'last_sleep_date', 'last_hevy_date',
               'bed_target', 'rise_target', 'debt_target_h', 'sleep_per_night_h'],
    'nights': ['date', 'week', 'weekday', 'sleep_h', 'bed', 'bed_late_min', 'rise',
               'rise_late_min', 'debt_h'],
    'weeks': _WEEK_COLS,
    'sets': _SET_COLS,
    'current': _WEEK_COLS + [f'prev_{c}' for c in _WEEK_COLS] + ['gap_h'],
    'sets_now': _SET_COLS,
    'freshness': ['name', 'last', 'behind', 'tolerance'],
    # 目標の一覧（1行1目標）。period は週・月を同じ表に並べるための列。link は行から飛ぶ画面の uid
    'goals_list': ['period', 'habit', 'metric', 'unit', 'target', 'this', 'prev', 'link'],
    # body / sleep / mind 画面。metrics_daily.csv に無い計算（FFMI・ステージ・ベースライン帯・運動）を持つ。
    # bed_h / wake_h は時計の時刻を数値にしたもの（入床は 12時より前なら +24。01:30 → 25.5）
    'daily': ['date',
              'weight', 'body_fat_rate', 'body_water_rate', 'muscle_kg', 'lbm_kg', 'ffmi',
              'cycling_min', 'cycling_hr', 'protein_g',
              'deep_min', 'light_min', 'rem_min', 'bed_h', 'wake_h', 'debt_h',
              'hrv', 'hrv_base', 'hrv_lo', 'hrv_hi', 'rhr', 'rhr_base', 'rhr_lo', 'rhr_hi',
              'spo2_avg', 'spo2_min'],
    # 消耗品画面（lib/consumables.py）
    'consumables': consumables.ITEM_COLUMNS,
    'consumable_purchases': consumables.PURCHASE_COLUMNS,
    # お金の画面（lib/assets.py）。assets_now は最新の1行（Grafana で最新を選ばせない）
    'assets': assets.ASSET_COLUMNS,
    'assets_now': assets.ASSET_COLUMNS,
    'goods': assets.GOODS_COLUMNS,
    # 口座別残高（lib/balances.py）。日次の合計と、口座ごとの最新
    'balances_daily': balances.DAILY_COLUMNS,
    'balances_now': balances.LATEST_COLUMNS,
    # 瞑想の画面（lib/meditation.py）。meditation_now は今週の1行（先週は prev_ 接頭辞）
    'meditation_daily': meditation.DAILY_COLUMNS,
    'meditation_weeks': meditation.WEEK_COLUMNS,
    'meditation_now': meditation.NOW_COLUMNS,
    'meditation_muse': meditation.MUSE_COLUMNS,
    'meditation_eval': meditation.EVAL_COLUMNS,
    # 筋トレの画面（lib/analytics/workout.py）。Hevy の記録が始まった週から今週まで、記録の無い週は 0
    'strength_weeks': ['week', 'week_start', 'days', 'workouts', 'minutes', 'volume_kg', 'reps', 'sets'],
    # 筋トレの画面の上の数値カード。1行1ワークアウトで、Grafana が時間範囲で絞って数える・足す。
    # start_ms は絞り込み式（${__from} / ${__to} はミリ秒）と比べるための列
    'strength_workouts': ['start', 'start_ms', 'minutes', 'volume_kg', 'reps', 'sets']
                         + [f'sets_{c}' for c in workout.MUSCLE_LABELS],
    'strength_sets': ['week', 'week_start', 'muscle', 'sets', 'target'],
    # 部位の一覧（Hevy の6部位の並び）。画面の部位の変数が読む。目標の無い部位は target が空
    'strength_muscles': ['muscle', 'target'],
    # 老化の画面（lib/longevity.py。台帳は config/longevity.yaml）。monthly の列は台帳の daily 指標の key
    'longevity_catalog': longevity.CATALOG_COLUMNS,
    'longevity_monthly': ['month'] + longevity.monthly_keys(longevity.load_registry()),
    'longevity_labs': longevity.LABS_COLUMNS,
}


def build_sets(week_labels: list[str], workouts_csv: Path = WORKOUTS_CSV):
    targets = workout.load_weekly_set_targets()
    if not workouts_csv.exists() or not targets:
        return [], None
    df = hevy_csv.parse_hevy_csv(workouts_csv)
    table, _ = workout.weekly_muscle_sets(df, workout.load_muscle_mapping(), week_labels)
    rows = []
    for wk in week_labels:
        for p in workout.weekly_set_progress(table, wk, targets):
            rows.append({'week': wk, 'muscle': p['label'], 'sets': p['actual'],
                         'target': p['target'], 'remaining': p['remaining']})
    for r in rows:
        r['axis_max'] = max([r['target']] + [x['sets'] for x in rows if x['muscle'] == r['muscle']])
    last = pd.to_datetime(df['start_dt']).max()
    return rows, (None if pd.isna(last) else last.date().isoformat())


def build_tables(today: dt.date, weeks: int, *, sleep_csv: Path = SLEEP_CSV,
                 steps_csv: Path = STEPS_CSV, workouts_csv: Path = WORKOUTS_CSV) -> dict[str, list[dict]]:
    """表の名前 → 行のリスト。読み込み先を引数で受けるので、ガードは呼び出し側（CLI）に置く"""
    monday = today - dt.timedelta(days=today.weekday())
    lo = monday - dt.timedelta(weeks=weeks - 1)
    bed_target, rise_target = get_target('bed_time'), get_target('rise_time')

    nights, week_rows = build_nights(lo, today, bed_target, rise_target, sleep_csv, steps_csv)
    week_labels = [w['week'] for w in week_rows]
    sets, last_hevy = build_sets(week_labels, workouts_csv)
    last_sleep = max((n['date'] for n in nights if n['sleep_h'] is not None), default=None)
    this_week = week_label(today)

    # 今週の行を Grafana の filter 式で選ばせない（判定がダッシュボード側に入るため）
    cur = next((w for w in week_rows if w['week'] == this_week), None)
    prev = week_rows[week_rows.index(cur) - 1] if cur and week_rows.index(cur) > 0 else None
    current = []
    if cur:
        row = dict(cur)
        for k, v in (prev or {k: None for k in cur}).items():
            row[f'prev_{k}'] = v
        row['gap_h'] = round(cur['total_h'] - cur['goal_h'], 1)
        current.append(row)

    return {
        'status': [{
            'generated_at': dt.datetime.now().astimezone().isoformat(timespec='minutes'),
            'today': today.isoformat(),
            'this_week': this_week,
            'last_sleep_date': last_sleep,
            'last_hevy_date': last_hevy,
            'bed_target': bed_target,
            'rise_target': rise_target,
            'debt_target_h': get_target('sleep_debt_h'),
            'sleep_per_night_h': SLEEP_PER_NIGHT_H,
        }],
        'nights': nights,
        'weeks': week_rows,
        'sets': sets,
        'current': current,
        'sets_now': [r for r in sets if r['week'] == this_week],
        'freshness': [
            {'name': r['name'], 'last': None if r['last'] is None else r['last'].date().isoformat(),
             'behind': r['behind'], 'tolerance': r['tolerance']}
            for r in collect_pipeline(today)
        ],
    }


def _clock_h(ts, evening: bool = False) -> float | None:
    if ts is None or pd.isna(ts):
        return None
    t = pd.Timestamp(ts)
    h = t.hour + t.minute / 60
    return round(h + 24 if evening and h < 12 else h, 2)


def _by_date(path: Path, date_col: str = 'date') -> pd.DataFrame:
    """日付 index（datetime.date）の DataFrame。無ければ空。同じ日が複数あれば最後の行"""
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df['_date'] = pd.to_datetime(df[date_col]).dt.date
    return df.drop_duplicates('_date', keep='last').set_index('_date')


def _num(df: pd.DataFrame, day: dt.date, col: str, digits: int = 1) -> float | None:
    if df.empty or day not in df.index or col not in df.columns:
        return None
    v = pd.to_numeric(df.at[day, col], errors='coerce')
    return None if pd.isna(v) else round(float(v), digits)


def _sport_by_day(sessions, calc) -> dict:
    stats = calc(sessions) if sessions is not None else None
    return {pd.Timestamp(r['date']).date(): r for r in (stats or {}).get('daily', [])}


def build_daily(lo: dt.date, hi: dt.date, *, sleep_csv: Path = SLEEP_CSV,
                innerscan_csv: Path = INNERSCAN_CSV, spo2_csv: Path = SPO2_CSV,
                nutrition_csv: Path = NUTRITION_CSV, exercise_csv: Path = EXERCISE_CSV) -> list[dict]:
    """body / sleep / mind 画面の日次表。データの無い日・指標は空セル（0にしない）

    体組成は body レポートと同じ healthplanet_innerscan.csv と body.prepare_body_df()。
    HRV / RHR のベースラインは STATE.md と同じ collect_daily_detail()（mind レポートと同じ関数・窓）。
    帯（lo / hi）は ±1SD。z の判定は Grafana でしない。
    """
    raw_sleep = pd.read_csv(sleep_csv)
    main = main_sleep(raw_sleep, lo, hi).set_index('date')
    debt = debt_by_day(raw_sleep, lo, hi)

    comp = _by_date(innerscan_csv)
    if not comp.empty:
        comp = body.prepare_body_df(comp)
    spo2 = _by_date(spo2_csv)
    nut = _by_date(nutrition_csv)
    sessions = exercise_source.load_sessions(lo, hi, csv_path=exercise_csv)
    cycling = _sport_by_day(sessions, activity.calc_cycling_stats_for_period)
    vitals = {r['date']: {c['label']: c for c in r['vitals']}
              for r in collect_daily_detail(hi, days=(hi - lo).days + 1)}

    rows = []
    for day in pd.date_range(lo, hi, freq='D').date:
        row = {c: None for c in COLUMNS['daily']}
        row['date'] = day.isoformat()
        for col, src, digits in (('weight', 'weight', 1), ('body_fat_rate', 'body_fat_rate', 1),
                                 ('body_water_rate', 'body_water_rate', 1), ('muscle_kg', 'muscle_mass', 1),
                                 ('lbm_kg', 'lbm', 1), ('ffmi', 'ffmi', 2)):
            row[col] = _num(comp, day, src, digits)
        # nutrition.csv は記録の無い日を 0 で持つ行がある。0 kcal は記録なしとして空にする
        if (_num(nut, day, 'calories') or 0) > 0:
            row['protein_g'] = _num(nut, day, 'protein')
        if day in cycling:
            row['cycling_min'] = cycling[day]['duration']
            hr = cycling[day]['avg_hr']
            row['cycling_hr'] = None if hr is None else round(hr)
        if day in main.index:
            r = main.loc[day]
            for col, src in (('deep_min', 'deepMinutes'), ('light_min', 'lightMinutes'), ('rem_min', 'remMinutes')):
                v = pd.to_numeric(r.get(src), errors='coerce')
                row[col] = None if pd.isna(v) else int(v)
            row['bed_h'] = _clock_h(pd.to_datetime(r['startTime']), evening=True)
            row['wake_h'] = _clock_h(pd.to_datetime(r['endTime']))
        row['debt_h'] = debt.get(day)
        for key, label, digits in (('hrv', 'HRV', 1), ('rhr', 'RHR', 1)):
            c = vitals.get(day, {}).get(label)
            if not c:
                continue
            row[key] = None if c['value'] is None else round(c['value'], digits)
            if c['baseline'] is not None:
                row[f'{key}_base'] = round(c['baseline'], 1)
                if c['std'] is not None:
                    row[f'{key}_lo'] = round(c['baseline'] - c['std'], 1)
                    row[f'{key}_hi'] = round(c['baseline'] + c['std'], 1)
        row['spo2_avg'] = _num(spo2, day, 'avg_spo2')
        row['spo2_min'] = _num(spo2, day, 'min_spo2')
        rows.append(row)
    return rows


def write_csvs(tables: dict[str, list[dict]], csv_dir: Path) -> list[Path]:
    """表ごとに全上書き。欠測（None）は空セルのまま書く（0にしない）"""
    ensure_dir(csv_dir)
    paths = []
    for name, rows in tables.items():
        path = require_private_write(csv_dir / f'{name}.csv')
        with path.open('w', newline='', encoding='utf-8') as f:
            # 行が0件でも見出しは残す。DictWriter は None を空セルで書く
            w = csv.DictWriter(f, fieldnames=COLUMNS[name])
            w.writeheader()
            w.writerows(rows)
        paths.append(path)
    return paths


def consumable_tables(today: dt.date) -> dict[str, list[dict]]:
    items, purchases = consumables.build(
        require_private_path(CONSUMABLES_CSV), require_private_path(PURCHASE_RULES_CSV),
        {k: require_private_path(v) for k, v in PURCHASE_CSVS.items()}, require_private_path(STOCKTAKE_CSV), today)
    return {'consumables': items, 'consumable_purchases': purchases}


def asset_tables() -> dict[str, list[dict]]:
    rows, goods = assets.build(require_private_path(MF_ASSETS_CSV), require_private_path(ITEMS_CSV),
                               require_private_path(MARKET_CSV))
    return {'assets': rows, 'assets_now': rows[-1:], 'goods': goods}


def balance_tables(today: dt.date) -> dict[str, list[dict]]:
    days, now = balances.build(require_private_path(MF_BALANCES_CSV), today)
    return {'balances_daily': days, 'balances_now': now}


def meditation_tables(today: dt.date) -> dict[str, list[dict]]:
    if not SATORU_SESSION_LOG.exists():
        raise SystemExit(f'{SATORU_SESSION_LOG} が無い（satoru を clone する）')
    muse = meditation.build_muse(SATORU_SESSION_LOG, require_private_path(METRICS_DAILY_CSV))
    return {**meditation.build(require_private_path(TOGGL_FOCUS_CSV), today), 'meditation_muse': muse,
            'meditation_eval': meditation.build_eval(muse, meditation.load_types())}


def strength_tables(today: dt.date, workouts_csv: Path = WORKOUTS_CSV) -> dict[str, list[dict]]:
    df = hevy_csv.parse_hevy_csv(require_private_path(workouts_csv))
    labels = workout.weeks_since(df['start_dt'].min(), today)
    table, _ = workout.weekly_muscle_sets(df, workout.load_muscle_mapping(), labels)
    stats = workout.weekly_training_stats(df, labels)
    targets = workout.load_weekly_set_targets()
    weeks, sets = [], []
    for wk in labels:
        start = dt.date.fromisocalendar(int(wk[:4]), int(wk[-2:]), 1).isoformat()
        weeks.append({'week': wk, 'week_start': start, 'days': int(table.loc[wk, 'training_days']),
                      **{k: int(v) for k, v in stats.loc[wk].items()}})
        for code, label in workout.MUSCLE_LABELS.items():
            n = int(table.loc[wk, code]) if code in table.columns else 0
            sets.append({'week': wk, 'week_start': start, 'muscle': label, 'sets': n, 'target': targets.get(code)})
    muscles = [{'muscle': label, 'target': targets.get(code)} for code, label in workout.MUSCLE_LABELS.items()]
    by_muscle = workout.session_muscle_sets(df, workout.load_muscle_mapping())
    workouts = []
    for r in workout.workout_sessions(df).itertuples():
        start = r.start_dt.tz_localize(JST)
        muscle = by_muscle.loc[r.start_dt] if r.start_dt in by_muscle.index else {}
        workouts.append({'start': start.isoformat(), 'start_ms': int(start.timestamp() * 1000), 'minutes': r.minutes,
                         'volume_kg': r.volume_kg, 'reps': r.reps, 'sets': r.sets,
                         **{f'sets_{c}': int(muscle[c]) if c in muscle else 0 for c in workout.MUSCLE_LABELS}})
    return {'strength_weeks': weeks, 'strength_sets': sets, 'strength_muscles': muscles,
            'strength_workouts': workouts}


WEEKDAYS = 5


def longevity_tables(today: dt.date) -> dict[str, list[dict]]:
    """老化の画面の3表。台帳の読み込み・計算は lib/longevity.py"""
    metrics = longevity.load_registry()

    def resolve(rel: str) -> Path:
        # ~/ はリポジトリ外（satoru の session_log。public なので private の検査を掛けない）
        if rel.startswith('~/'):
            return Path(rel).expanduser()
        return require_private_path(project_root / rel)

    obs = longevity.read_observations(metrics, resolve)
    return {'longevity_catalog': longevity.build_catalog(metrics, obs),
            'longevity_monthly': longevity.build_monthly(metrics, obs, today),
            'longevity_labs': longevity.build_labs(metrics, obs)}


def habit_goal_rows(habits: list[dict], this_week: str, prev_week: str) -> list[dict]:
    """習慣ごとに1行（lib/habits/weekly.weekly_days の結果を並べ替えるだけで、ここでは数えない）"""
    return [{'period': '週', 'habit': h['habit'], 'metric': f"{h['habit']} (日)", 'unit': '日',
             'target': h['target'], 'this': h['days'].get(this_week), 'prev': h['days'].get(prev_week),
             'link': None}
            for h in habits]


def goal_list(tables: dict[str, list[dict]], habits: list[dict], prev_week: str) -> list[dict]:
    """目標の画面の表。目標と今週・先週の実績を1行に並べる（達成の判定や色はつけない）

    スマホ幅で4列（項目・目標・今週・先週）に収めるため、metric に習慣名と単位を含める。
    habits は lib/habits/weekly.weekly_days の結果（今週・先週を含む）"""
    status = tables['status'][0]
    cur = tables['current'][0] if tables['current'] else {}
    rows = [
        ('早起き', f"入床 {status['bed_target']}まで (平日)", '日', WEEKDAYS, 'bed_hit', 'early-rising'),
        ('早起き', f"離床 {status['rise_target']}まで (平日)", '日', WEEKDAYS, 'rise_hit', 'early-rising'),
        ('睡眠', '睡眠 1晩の平均 (h)', 'h', status['sleep_per_night_h'], 'avg_h', 'early-rising'),
        ('睡眠', '睡眠負債 週末 (h)', 'h', status['debt_target_h'], 'debt_end_h', 'early-rising'),
    ]
    out = [{'period': '週', 'habit': h, 'metric': m, 'unit': u, 'target': t,
            'this': cur.get(k), 'prev': cur.get(f'prev_{k}'), 'link': link}
           for h, m, u, t, k, link in rows]
    sets = {(r['week'], r['muscle']): r for r in tables['sets']}
    for r in tables['sets_now']:
        prev = sets.get((cur.get('prev_week'), r['muscle']), {})
        out.append({'period': '週', 'habit': '筋トレ', 'metric': f"筋トレ {r['muscle']} (セット)", 'unit': 'セット',
                    'target': r['target'], 'this': r['sets'], 'prev': prev.get('sets'), 'link': 'strength'})
    out += habit_goal_rows(habits, status['this_week'], prev_week)
    return out


def load_habit_weeks(today: dt.date) -> tuple[list[dict], str]:
    """今週・先週の習慣ごとの日数（weekly_days）と先週のキー"""
    this_week, prev_week = habits_weekly.week_key(today), habits_weekly.week_key(today - dt.timedelta(weeks=1))
    habits = habits_weekly.weekly_days(habits_config.load_daily(), toggl_focus.load_projects(),
                                       habits_config.load_clients(), habits_config.load_roster(),
                                       [prev_week, this_week])
    return habits, prev_week


def goal_tables(today: dt.date, weeks: int) -> dict[str, list[dict]]:
    tables = build_tables(today, weeks)
    habits, prev_week = load_habit_weeks(today)
    tables['goals_list'] = goal_list(tables, habits, prev_week)
    return tables


# 画面ごとの表のまとまり。新しい画面はここに1グループ足す（サブコマンドを増やさない）
GROUPS = {
    'goals': lambda today, weeks: goal_tables(today, weeks),
    'daily': lambda today, weeks: {'daily': build_daily(today - dt.timedelta(days=DAILY_DAYS - 1), today)},
    'consumables': lambda today, weeks: consumable_tables(today),
    'assets': lambda today, weeks: asset_tables(),
    'balances': lambda today, weeks: balance_tables(today),
    'meditation': lambda today, weeks: meditation_tables(today),
    'strength': lambda today, weeks: strength_tables(today),
    'longevity': lambda today, weeks: longevity_tables(today),
}


def build_groups(names, today: dt.date, weeks: int = 8) -> dict[str, list[dict]]:
    """names のグループの表をまとめて返す"""
    if {'goals', 'daily'} & set(names):
        # 読み込み元の symlink 未マウントは「データなし」で正常終了して欠測を捏造するので、ここで落とす
        require_private_path(SLEEP_CSV)
    tables = {}
    for name in names:
        tables.update(GROUPS[name](today, weeks))
    return tables


def _groups_arg(value: str) -> list[str]:
    names = [v.strip() for v in value.split(',') if v.strip()]
    unknown = [n for n in names if n not in GROUPS]
    if unknown or not names:
        raise argparse.ArgumentTypeError(f'不明なグループ: {",".join(unknown) or repr(value)}（{",".join(GROUPS)}）')
    return names


def cmd_build(args) -> int:
    tables = build_groups(args.only or list(GROUPS), dt.date.today(), args.weeks)
    written = write_csvs(tables, Path(args.csv_dir))
    if 'status' in tables:
        out = {k: tables[k] for k in ('status', 'nights', 'weeks', 'sets')}
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
        counts = ' '.join(f'{k}={len(tables[k])}' for k in ('nights', 'weeks', 'sets', 'daily') if k in tables)
        print(f'{path}  {counts}', file=sys.stderr)
    for p in written:
        print(f'  {p}', file=sys.stderr)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='ダッシュボード用の JSON と Grafana 用の CSV を書き出す')
    b.add_argument('--only', type=_groups_arg, help=f'作るグループをカンマ区切りで（{",".join(GROUPS)}）。省略で全部')
    b.add_argument('--weeks', type=int, default=8)
    b.add_argument('--out', default=str(project_root / 'tmp/dashboard/goals.json'))
    b.add_argument('--csv-dir', default=str(CSV_DIR))
    b.set_defaults(func=cmd_build)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
