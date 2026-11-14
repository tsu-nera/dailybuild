#!/usr/bin/env python3
"""
週の目標ダッシュボード（claude.ai の Artifact）に載せる数値を JSON に書き出す

ページ（scripts/dashboard/index.html）は数値を持たない。数値はこの JSON 1本で、
Artifact へは agent が添付ファイルとして上げ直す（スクリプトからは公開できない）。
目標値は config/targets.yaml（睡眠）と config/exercise_muscles.yaml の weekly_sets（筋トレ）
から読むので、目標を書き換えればダッシュボードも追随する。

同じ数値を Grafana 用の CSV 7本（nights / weeks / sets / status / current / sets_now /
freshness）としても reports/dashboard/ へ全上書きで書く（docs/grafana.md）。欠測は空セル。
加えて Body / Sleep / Mind 画面用の daily.csv（直近 DAILY_DAYS 日、1日1行）と、
消耗品画面用の consumables.csv / consumable_purchases.csv（lib/consumables.py）、
お金の画面用の assets.csv / assets_now.csv / goods.csv（lib/assets.py）、
瞑想の画面用の meditation_{sessions,daily,weeks,now,muse}.csv（lib/meditation.py。muse は satoru の session_log）を書く。
計算はここに1本で、Grafana 側では集計も判定もしない。

Usage:
    uv run scripts/dashboard.py build [--only goals,daily,consumables,assets,meditation] [--weeks 8]
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

from lib import assets, consumables, exercise_source, hevy_csv, meditation  # noqa: E402
from lib.analytics import activity, body  # noqa: E402
from lib.analytics import sleep as sleep_lib  # noqa: E402
from lib.analytics import workout  # noqa: E402
from lib.analytics.sleep.rise import load_steps, minutes_late, rise_time  # noqa: E402
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
SATORU_SESSION_LOG = Path.home() / 'repo/satoru/logs/session_log.csv'  # satoru（PUBLIC）。vaio で pull して読む
CONSUMABLES_CSV = project_root / 'data/inventory/consumables.csv'
PURCHASE_RULES_CSV = project_root / 'data/inventory/purchase_rules.csv'
STOCKTAKE_CSV = project_root / 'data/inventory/stocktake.csv'
MF_ASSETS_CSV = project_root / 'data/mf/資産推移.csv'
ITEMS_CSV = project_root / 'data/inventory/items.csv'
MARKET_CSV = project_root / 'data/inventory/market.csv'
PURCHASE_CSVS = {'amazon': project_root / 'data/purchases/amazon.csv',
                 'myprotein': project_root / 'data/purchases/myprotein.csv',
                 'rakuten': project_root / 'data/purchases/rakuten.csv',
                 'store': project_root / 'data/purchases/store.csv'}

# daily.csv の期間。推移は Grafana の時間範囲で絞るので、表は長めに持つ
DAILY_DAYS = 365

# 週の睡眠時間の目安。bed_time の宣言（rise_time − 睡眠7時間 − 入眠15分）と同じ7時間
SLEEP_PER_NIGHT_H = 7

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
    # Body / Sleep / Mind 画面。metrics_daily.csv に無い計算（FFMI・ステージ・ベースライン帯・運動）を持つ。
    # bed_h / wake_h は時計の時刻を数値にしたもの（入床は 12時より前なら +24。01:30 → 25.5）
    'daily': ['date',
              'weight', 'body_fat_rate', 'body_water_rate', 'muscle_kg', 'lbm_kg', 'ffmi',
              'cycling_min', 'cycling_hr', 'strength_min', 'protein_g',
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
    # 瞑想の画面（lib/meditation.py）。meditation_now は今週の1行（先週は prev_ 接頭辞）
    'meditation_sessions': meditation.SESSION_COLUMNS,
    'meditation_daily': meditation.DAILY_COLUMNS,
    'meditation_weeks': meditation.WEEK_COLUMNS,
    'meditation_now': meditation.NOW_COLUMNS,
    'meditation_muse': meditation.MUSE_COLUMNS,
}


def _week_label(d: dt.date) -> str:
    iso = d.isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


def _hm(ts) -> str | None:
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime('%H:%M')


def _main_sleep(raw: pd.DataFrame, lo: dt.date, hi: dt.date) -> pd.DataFrame:
    df = raw[raw['isMainSleep'].astype(str).str.lower().isin(['true', '1'])].copy()
    df['date'] = pd.to_datetime(df['dateOfSleep']).dt.date
    df = df[(df['date'] >= lo) & (df['date'] <= hi)]
    # 同じ日に主睡眠が2本ある日は長い方（重なりセッションは取得側で除外済み）
    return df.sort_values('minutesAsleep').drop_duplicates('date', keep='last').sort_values('date')


def _debt_by_day(raw: pd.DataFrame, lo: dt.date, hi: dt.date) -> dict:
    """journal_skeleton と同じ build_debt_calculator。片方だけ条件を変えると負債が2つになる"""
    calc = sleep_lib.build_debt_calculator(raw)
    out = {}
    for day in pd.date_range(lo, hi, freq='D'):
        try:
            r = calc.calculate(end_date=day, weight_method=sleep_lib.DEBT_WEIGHT_METHOD)
        except ValueError:
            continue
        out[day.date()] = round(r.sleep_debt_hours, 1)
    return out


def build_sleep(lo: dt.date, hi: dt.date, bed_target: str | None, rise_target: str | None,
                sleep_csv: Path = SLEEP_CSV, steps_csv: Path = STEPS_CSV):
    raw = pd.read_csv(sleep_csv)
    df = _main_sleep(raw, lo, hi)
    steps = load_steps(steps_csv) if steps_csv.exists() else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    debt = _debt_by_day(raw, lo, hi)
    by_date = {r['date']: r for _, r in df.iterrows()}

    nights = []
    for day in pd.date_range(lo, hi, freq='D').date:
        r = by_date.get(day)
        row = {'date': day.isoformat(), 'week': _week_label(day), 'weekday': day.weekday() < 5,
               'sleep_h': None, 'bed': None, 'bed_late_min': None,
               'rise': None, 'rise_late_min': None, 'debt_h': debt.get(day)}
        if r is not None:
            start = pd.to_datetime(r['startTime'])
            wakeup = pd.to_datetime(r['endTime']) - pd.Timedelta(minutes=r['minutesAfterWakeup'] or 0)
            rise = rise_time(steps, wakeup)
            row.update({
                'sleep_h': round(r['minutesAsleep'] / 60, 1),
                'bed': _hm(start),
                'bed_late_min': minutes_late(start, bed_target, evening=True) if bed_target else None,
                'rise': _hm(rise),
                'rise_late_min': minutes_late(rise, rise_target) if rise_target and rise is not None else None,
            })
        nights.append(row)

    weeks = []
    for wk in dict.fromkeys(n['week'] for n in nights):
        ns = [n for n in nights if n['week'] == wk]
        rec = [n for n in ns if n['sleep_h'] is not None]
        bed = [n for n in ns if n['weekday'] and n['bed_late_min'] is not None]
        rise = [n for n in ns if n['weekday'] and n['rise_late_min'] is not None]
        debts = [n['debt_h'] for n in ns if n['debt_h'] is not None]
        weeks.append({
            'week': wk,
            'days': len(ns),
            'nights': len(rec),
            'total_h': round(sum(n['sleep_h'] for n in rec), 1),
            # 欠測の夜は0として足さない。目安は記録のある夜の数 × 7h
            'goal_h': len(rec) * SLEEP_PER_NIGHT_H,
            'avg_h': round(sum(n['sleep_h'] for n in rec) / len(rec), 1) if rec else None,
            'bed_hit': sum(n['bed_late_min'] <= 0 for n in bed), 'bed_n': len(bed),
            'rise_hit': sum(n['rise_late_min'] <= 0 for n in rise), 'rise_n': len(rise),
            'debt_end_h': debts[-1] if debts else None,
        })
    return nights, weeks


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

    nights, week_rows = build_sleep(lo, today, bed_target, rise_target, sleep_csv, steps_csv)
    week_labels = [w['week'] for w in week_rows]
    sets, last_hevy = build_sets(week_labels, workouts_csv)
    last_sleep = max((n['date'] for n in nights if n['sleep_h'] is not None), default=None)
    this_week = _week_label(today)

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
    """Body / Sleep / Mind 画面の日次表。データの無い日・指標は空セル（0にしない）

    体組成は body レポートと同じ healthplanet_innerscan.csv と body.prepare_body_df()。
    HRV / RHR のベースラインは STATE.md と同じ collect_daily_detail()（mind レポートと同じ関数・窓）。
    帯（lo / hi）は ±1SD。z の判定は Grafana でしない。
    """
    raw_sleep = pd.read_csv(sleep_csv)
    main = _main_sleep(raw_sleep, lo, hi).set_index('date')
    debt = _debt_by_day(raw_sleep, lo, hi)

    comp = _by_date(innerscan_csv)
    if not comp.empty:
        comp = body.prepare_body_df(comp)
    spo2 = _by_date(spo2_csv)
    nut = _by_date(nutrition_csv)
    sessions = exercise_source.load_sessions(lo, hi, csv_path=exercise_csv)
    cycling = _sport_by_day(sessions, activity.calc_cycling_stats_for_period)
    strength = _sport_by_day(sessions, activity.calc_strength_stats_for_period)
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
        if day in strength:
            row['strength_min'] = strength[day]['duration']
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


def meditation_tables(today: dt.date) -> dict[str, list[dict]]:
    if not SATORU_SESSION_LOG.exists():
        raise SystemExit(f'{SATORU_SESSION_LOG} が無い（satoru を clone する）')
    return {**meditation.build(require_private_path(TOGGL_FOCUS_CSV), today),
            'meditation_muse': meditation.build_muse(SATORU_SESSION_LOG)}


# 画面ごとの表のまとまり。新しい画面はここに1グループ足す（サブコマンドを増やさない）
GROUPS = {
    'goals': lambda today, weeks: build_tables(today, weeks),
    'daily': lambda today, weeks: {'daily': build_daily(today - dt.timedelta(days=DAILY_DAYS - 1), today)},
    'consumables': lambda today, weeks: consumable_tables(today),
    'assets': lambda today, weeks: asset_tables(),
    'meditation': lambda today, weeks: meditation_tables(today),
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
