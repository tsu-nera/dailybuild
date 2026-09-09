#!/usr/bin/env python
# coding: utf-8
"""Habitica（習慣管理）

日付をまたぐ処理（Habitica 用語で cron）を毎日確定させる。Daily の未完了は
この処理でしか history に記録されないため、走らせない日は「未達」ではなく
「欠測」になり、達成率の分母が作れない。

Usage:
    python scripts/habitica.py cron     # cron を確定させ、実行を記録する
    python scripts/habitica.py fetch    # Habit / Daily の history を CSV に落とす
    python scripts/habitica.py show     # 週ごとの回数・達成をまとめて出す
    python scripts/habitica.py status   # 現在の状態を表示（何も変更しない）

詳細と落とし穴は docs/habitica.md を参照。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import json
import logging

import pandas as pd
import yaml

from lib.clients.habitica_client import HabiticaClient, HabiticaError, creds_path
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = creds_path()
CRON_LOG = BASE_DIR / 'data' / 'habitica' / 'cron_log.csv'
HISTORY_CSV = BASE_DIR / 'data' / 'habitica' / 'history.csv'
TASKS_JSON = BASE_DIR / 'data' / 'habitica' / 'tasks.json'

COLUMNS = [
    'date', 'ran_at', 'last_cron_prev', 'last_cron_get', 'needs_cron',
    'cron_posted', 'last_cron_final', 'hp', 'lvl', 'exp', 'gp',
]

# Habit と Daily で history の中身が違うので、両方の列を持たせて片方を空にする。
# Daily: {date, value, isDue, completed} / Habit: {date, value, scoredUp, scoredDown}
HISTORY_COLUMNS = [
    'date', 'ts', 'task_id', 'task_type', 'task_name',
    'value', 'is_due', 'completed', 'scored_up', 'scored_down',
]
HISTORY_KEY = ['date', 'task_id']

HABITS_DAILY_CSV = BASE_DIR / 'reports' / 'habits_daily.csv'
HABITS_DAILY_COLUMNS = ['date', 'habit', 'task_type', 'is_due', 'completed']

DAY_START_HOUR = 5          # Habitica の dayStart。0時またぎを畳まないための起点
VARIABILITY_MIN_POINTS = 8  # これ未満の点数では変動性を出さない

# 習慣名そのものが非公開なので private 側に置く（dailybuild は public）
HABITS_YAML = require_private_path(BASE_DIR / 'config' / 'private' / 'habits.yaml')
GRADUATED_TAG = '卒業'

logger = logging.getLogger(__name__)


def habitica_date(now: dt.datetime, day_start_hour: int) -> dt.date:
    """Habitica 上の「その日」を返す。dayStart（既定5時）より前は前日扱い。"""
    return (now - dt.timedelta(hours=day_start_hour)).date()


def load_cron_log() -> pd.DataFrame:
    if not CRON_LOG.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(CRON_LOG, dtype={'date': str})


def save_cron_log(df: pd.DataFrame, row: dict) -> pd.DataFrame:
    """同じ date の行は上書きする（同日に複数回走らせても重複させない）"""
    df = df[df['date'] != row['date']] if not df.empty else df
    merged = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    merged = merged[COLUMNS].sort_values('date').reset_index(drop=True)
    ensure_dir(CRON_LOG.parent)
    merged.to_csv(CRON_LOG, index=False)
    return merged


def run_cron(client: HabiticaClient) -> dict:
    """cron を確定させ、1行ぶんの記録を返す"""
    log = load_cron_log()
    last_cron_prev = log['last_cron_final'].iloc[-1] if not log.empty else ''

    user = client.get_user()
    day_start = int(user.get('preferences', {}).get('dayStart', 0))
    last_cron_get = user.get('lastCron', '')
    needs_cron = bool(user.get('needsCron'))

    if needs_cron:
        after = client.run_cron()
        last_cron_final = after.get('user', after).get('lastCron', last_cron_get)
        stats = after.get('user', after).get('stats', user.get('stats', {}))
    else:
        last_cron_final = last_cron_get
        stats = user.get('stats', {})

    now = dt.datetime.now()
    row = {
        'date': habitica_date(now, day_start).isoformat(),
        'ran_at': now.replace(microsecond=0).isoformat(),
        'last_cron_prev': last_cron_prev,
        'last_cron_get': last_cron_get,
        'needs_cron': needs_cron,
        'cron_posted': needs_cron,
        'last_cron_final': last_cron_final,
        'hp': round(float(stats.get('hp', 0)), 2),
        'lvl': stats.get('lvl'),
        'exp': stats.get('exp'),
        'gp': round(float(stats.get('gp', 0)), 2),
    }
    save_cron_log(log, row)
    return row


def cmd_cron(_args) -> int:
    require_private_path(CRON_LOG)
    client = HabiticaClient.from_config(CREDS_FILE)
    row = run_cron(client)

    if row['cron_posted']:
        print(f"cron を実行しました（{row['last_cron_get']} → {row['last_cron_final']}）")
    elif row['last_cron_prev'] and row['last_cron_get'] != row['last_cron_prev']:
        # 前回の記録より進んでいるのに needsCron が False。GET だけで走ったか、
        # 人がアプリを開いて走らせたか。どちらでも分母は積まれている
        print(f"cron は既に実行済み（{row['last_cron_prev']} → {row['last_cron_get']}）")
    else:
        print(f"cron の実行は不要（lastCron={row['last_cron_get']}）")

    print(f"{row['date']}  HP={row['hp']} Lv{row['lvl']} exp={row['exp']} gp={row['gp']}")
    print(f"記録: {CRON_LOG}")
    return 0


def load_history() -> pd.DataFrame:
    if not HISTORY_CSV.exists():
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    return pd.read_csv(
        HISTORY_CSV,
        dtype={'date': str, 'ts': str, 'task_id': str, 'task_type': str, 'task_name': str},
    )


def history_rows(tasks: list, task_type: str) -> list:
    """タスクの history を1エントリ1行に展開する"""
    rows = []
    for task in tasks:
        for entry in task.get('history') or []:
            ts = dt.datetime.fromtimestamp(entry['date'] / 1000)
            rows.append({
                'date': ts.date().isoformat(),
                'ts': ts.replace(microsecond=0).isoformat(),
                'task_id': task['id'],
                'task_type': task_type,
                'task_name': task.get('text', ''),
                'value': round(float(entry.get('value', 0)), 4),
                'is_due': entry.get('isDue'),
                'completed': entry.get('completed'),
                'scored_up': entry.get('scoredUp'),
                'scored_down': entry.get('scoredDown'),
            })
    return rows


def merge_history(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """(date, task_id) をキーに、新しい行だけを差し替える。

    **API に無い task_id の行は消さない。** Habitica はタスクを削除すると
    history ごと消えるので、API の結果で全上書きすると過去の記録まで一緒に
    失われる（削除は取り消せないので欠測の捏造になる）。

    Daily は**同じ日に2エントリ届く**（cron 時に completed=False、その後
    本人が完了すると completed=True がもう1行）。1日1行に畳まないとキーが
    一意にならないので、その日の最後の ts を採る。
    """
    old = old.reindex(columns=HISTORY_COLUMNS) if not old.empty else old
    if old.empty:
        merged = new
    elif new.empty:
        merged = old
    else:
        replaced = pd.MultiIndex.from_frame(old[HISTORY_KEY]).isin(
            pd.MultiIndex.from_frame(new[HISTORY_KEY])
        )
        merged = pd.concat([old[~replaced], new], ignore_index=True)
    merged = merged.reindex(columns=HISTORY_COLUMNS)
    merged = merged.sort_values(HISTORY_KEY + ['ts']).drop_duplicates(HISTORY_KEY, keep='last')
    return merged.sort_values(['date', 'task_type', 'task_name']).reset_index(drop=True)


def fetch_history(client: HabiticaClient) -> tuple:
    """Habit / Daily を取得し、(マージ後の history, タスクの生データ) を返す"""
    tasks = {
        'habits': client.get_tasks('habits'),
        'dailys': client.get_tasks('dailys'),
        'tags': client.get_tags(),   # タスク側は tag の id しか持たない
    }
    new = pd.DataFrame(
        history_rows(tasks['habits'], 'habit') + history_rows(tasks['dailys'], 'daily'),
        columns=HISTORY_COLUMNS,
    )
    return merge_history(load_history(), new), tasks, new


def habits_daily(hist: pd.DataFrame, roster: dict, tasks: dict) -> pd.DataFrame:
    """日次グレインの派生（`reports/habits_daily.csv` の中身）。

    roster（`config/private/habits.yaml` の `habits`）に載っている名前だけを対象にし、
    出力の `habit` 列には roster 側の名前（＝現在の Habitica 上の名前）を入れる。
    history 側の `task_name` は使わない（リネームで割れるため）。

    **`history` に行が無い日の行を作らない。** cron が走らなかった日は「不生起」
    ではなく欠測なので、日付の穴埋め・reindex を一切しない。
    """
    by_name = {t.get('text', ''): t for t in tasks.get('habits', []) + tasks.get('dailys', [])}
    id_to_name = {by_name[name]['id']: name for name in roster if name in by_name}
    if hist.empty or not id_to_name:
        return pd.DataFrame(columns=HABITS_DAILY_COLUMNS)

    df = hist[hist['task_id'].isin(id_to_name)].copy()
    if df.empty:
        return pd.DataFrame(columns=HABITS_DAILY_COLUMNS)

    # (date, task_id) で最後の ts を採って畳む（merge_history と同じ規則。
    # cron 行 completed=False と完了行 completed=True が同日に並ぶことがある）
    df = (df.sort_values(['date', 'task_id', 'ts'])
            .drop_duplicates(['date', 'task_id'], keep='last'))

    is_daily = df['task_type'] == 'daily'
    is_due = pd.Series(None, index=df.index, dtype=object)
    completed = pd.Series(None, index=df.index, dtype=object)
    # habit の行は分母が原理的に無いので is_due/completed を空のままにする（0埋め禁止）
    is_due[is_daily] = df.loc[is_daily, 'is_due'].astype(str) == 'True'
    completed[is_daily] = df.loc[is_daily, 'completed'].astype(str) == 'True'

    out = pd.DataFrame({
        'date': df['date'],
        'habit': df['task_id'].map(id_to_name),
        'task_type': df['task_type'],
        'is_due': is_due,
        'completed': completed,
    })
    return (out.sort_values(['date', 'habit'])
               .reset_index(drop=True))[HABITS_DAILY_COLUMNS]


def cmd_fetch(_args) -> int:
    require_private_path(HISTORY_CSV)
    require_private_path(TASKS_JSON)
    require_private_path(HABITS_DAILY_CSV)
    client = HabiticaClient.from_config(CREDS_FILE)

    old = load_history()
    merged, tasks, new = fetch_history(client)

    ensure_dir(HISTORY_CSV.parent)
    merged.to_csv(HISTORY_CSV, index=False)
    # 全上書きのスナップショット。削除されたタスクの復元用（private の git が世代を持つ）
    TASKS_JSON.write_text(json.dumps(tasks, ensure_ascii=False, indent=1))

    roster = load_config().get('habits') or {}
    daily = habits_daily(merged, roster, tasks)
    ensure_dir(HABITS_DAILY_CSV.parent)
    daily.to_csv(HABITS_DAILY_CSV, index=False)

    added = len(merged) - len(old)
    live = set(new['task_id']) if not new.empty else set()
    gone = sorted(set(merged['task_id']) - live) if not merged.empty else []

    print(f"Habit {len(tasks['habits'])}件 / Daily {len(tasks['dailys'])}件 を取得しました")
    print(f"history: {len(merged)}行（新規 {added}行）  {HISTORY_CSV}")
    print(f"tasks  : {TASKS_JSON}")
    print(f"habits : {len(daily)}行  {HABITS_DAILY_CSV}")
    if gone:
        # Habitica 上には無いが CSV には残っている＝削除されたタスク。消さずに残す
        names = merged[merged['task_id'].isin(gone)].groupby('task_id')['task_name'].last()
        print(f"\nHabitica 上に存在しないタスクの記録を {len(gone)}件保持しています:")
        for task_id, name in names.items():
            print(f"  {name}（{task_id}）")
    return 0


def load_config() -> dict:
    """対象と目標値。**無ければ落とす。**

    空の dict を返すと全習慣が黙って「対象外」になり、レビューが何も出ないまま
    正常終了する。設定を見失ったことに気づけないので、例外にする。
    """
    if not HABITS_YAML.exists():
        raise FileNotFoundError(
            f'習慣の設定がありません: {HABITS_YAML}\n'
            f'dailybuild-private の config/habits.yaml を確認してください。')
    return yaml.safe_load(HABITS_YAML.read_text()) or {}


def graduated_ids(tasks: dict) -> set:
    """Tag「卒業」が付いたタスクの id。**除外の条件はこれだけ。**

    value が高いだけで黙って外すと、外れたことに気づけない。value は候補の
    提示に使い、実際に外すのは Tag を付ける操作（本人の明示）に限る。
    """
    tag_ids = {t['id'] for t in tasks.get('tags', []) if t.get('name') == GRADUATED_TAG}
    if not tag_ids:
        return set()
    return {
        t['id']
        for t in tasks.get('habits', []) + tasks.get('dailys', [])
        if tag_ids & set(t.get('tags') or [])
    }


def week_keys(end: dt.date, weeks: int) -> list:
    """新しい順に ISO 週キーを返す"""
    mondays = [end - dt.timedelta(days=end.weekday() + 7 * i) for i in range(weeks)]
    return [m.strftime('%G-W%V') for m in reversed(mondays)]


def _iso_week(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.strftime('%G-W%V')


def _weekly(hist: pd.DataFrame, weeks: list, column: str) -> pd.DataFrame:
    """task_id × 週の合計。行が無い週は 0"""
    if hist.empty:
        return pd.DataFrame(columns=weeks)
    df = hist.assign(week=_iso_week(hist['date']))
    return (df.pivot_table(index='task_id', columns='week', values=column, aggfunc='sum')
            .reindex(columns=weeks).fillna(0).astype(int))


def tracked_habits(roster: dict, tasks: list, direction: str) -> list:
    """roster（yaml）に載っていて `track` が direction のものだけを返す。

    **行は roster 起点で作る。** history 起点にすると、一度も押していない習慣が
    表から消える。これから形成する習慣ほど消えるので、0 が見えないと困る。
    """
    by_name = {t.get('text', ''): t for t in tasks}
    return [by_name[name] for name, spec in roster.items()
            if spec.get('track') == direction and name in by_name]


def missing_from_habitica(roster: dict, tasks: list) -> list:
    """yaml が対象に指定しているのに Habitica に無い名前。

    リネームや削除で黙って対象から落ちるのを防ぐ。飛ばさずに名指しで出す。
    Habit と Daily を混ぜて渡すこと（yaml は型を区別せず名前で指定する）。
    """
    names = {t.get('text', '') for t in tasks}
    return sorted(name for name in roster if name not in names)


def tracked_dailys(roster: dict, tasks: list) -> list:
    """Daily も roster に書いたものだけを見る。

    以前は Daily を常に全件出していた（cron が毎日行を書くので押し忘れが穴に
    ならない、という理由）。だが「記録が信用できるか」と「レビューしたいか」は
    別の問題で、家事の Daily まで毎週表に出ても読む対象が薄まるだけだった。
    """
    return [t for t in tasks if t.get('text', '') in roster]


def habit_table(hist: pd.DataFrame, weeks: list, roster: dict,
                tasks: list, direction: str) -> pd.DataFrame:
    """Habit は回数。scored_up / scored_down が1日の押下回数（実測で最大4）。"""
    picked = tracked_habits(roster, tasks, direction)
    if not picked:
        return pd.DataFrame()
    column = 'scored_up' if direction == 'up' else 'scored_down'
    counts = _weekly(hist[hist['task_type'] == 'habit'], weeks, column)
    table = counts.reindex([t['id'] for t in picked]).fillna(0).astype(int)
    table.index = [t.get('text', '') for t in picked]
    table.index.name = '習慣'
    if direction == 'up':
        # 「減らす」は評価の対象にしないので目標も持たせない
        table['目標'] = [roster[name].get('target_per_week') or '-' for name in table.index]
    return table


def last_pressed(hist: pd.DataFrame, tasks: list, today: dt.date) -> list:
    """(名前, 最終押下日, 経過日数)。押下が一度も無ければ日付は None。

    週あたりの回数だけだと、窓（既定4週）より古い空白が「0 が4つ」に化けて
    見えなくなる。実際 2年押されていない習慣が W34-W37 の全 0 に紛れていた。
    行動についてではなく**記録について**の文なので、「N日やっていない」とは読まない。
    """
    h = hist[hist['task_type'] == 'habit']
    pressed = h[(h['scored_up'].fillna(0) > 0) | (h['scored_down'].fillna(0) > 0)]
    rows = []
    for t in tasks:
        own = pressed[pressed['task_id'] == t['id']]
        if own.empty:
            rows.append((t.get('text', ''), None, None))
            continue
        day = pd.to_datetime(own['date']).max().date()
        rows.append((t.get('text', ''), day, (today - day).days))
    return rows


def daily_table(hist: pd.DataFrame, weeks: list, tasks: list,
                roster: dict | None = None) -> pd.DataFrame:
    """Daily は 完了/due。**分母は is_due の行数**で、記録が無い日は欠測。

    Habitica の Daily は「週x回」を表現できない（frequency は曜日か everyX のみ）。
    そこで repeat を全曜日にして毎日 due にし、**週何回を目標にするかは
    `config/habits.yaml` の target_per_week で持つ**。曜日固定にすると、動けない
    日に未達が確定して融通が利かない。
    """
    if not tasks:
        return pd.DataFrame()
    due = hist[(hist['task_type'] == 'daily') & (hist['is_due'].astype(str) == 'True')]
    done = _weekly(due.assign(done=due['completed'].astype(str) == 'True'), weeks, 'done')
    total = _weekly(due.assign(n=1), weeks, 'n')

    ids = [t['id'] for t in tasks]
    done = done.reindex(ids).fillna(0).astype(int)
    total = total.reindex(ids).fillna(0).astype(int)
    # 0除算を避けるため分母0の行は1に逃がす（値は捨てる。セルは直後に '-' で上書きされる）
    pct = (100 * done / total.mask(total == 0, 1)).round().astype(int)
    cell = done.astype(str) + '/' + total.astype(str) + ' (' + pct.astype(str) + '%)'
    table = cell.where(total > 0, '-')
    table.index = [t.get('text', '') for t in tasks]
    table.index.name = '習慣'
    if roster:
        table['目標'] = [(roster.get(name) or {}).get('target_per_week') or '-'
                         for name in table.index]
    return table


def press_rows(hist: pd.DataFrame) -> pd.DataFrame:
    """『押下』とみなす行だけを取り出す。

    habit: `scored_up` または `scored_down` が 0 より大きい行。
    daily: `completed` が True の行（cron が書く completed=False は押下ではない）。
    """
    if hist.empty:
        return hist
    is_habit = hist['task_type'] == 'habit'
    is_daily = hist['task_type'] == 'daily'
    pressed_habit = is_habit & ((hist['scored_up'].fillna(0) > 0) | (hist['scored_down'].fillna(0) > 0))
    pressed_daily = is_daily & (hist['completed'].astype(str) == 'True')
    return hist[pressed_habit | pressed_daily]


def minutes_since_day_start(ts: pd.Series, day_start_hour: int = DAY_START_HOUR) -> pd.Series:
    """押下時刻を dayStart 起点の経過分に直す。23:50 と 00:10 を最大距離にしないため。"""
    t = pd.to_datetime(ts)
    return ((t.dt.hour * 60 + t.dt.minute) - day_start_hour * 60) % 1440


def rhythm_table(hist: pd.DataFrame, weeks: list, tasks: list) -> pd.DataFrame:
    """窓全体（weeks の範囲）で1つずつ出す、時刻の変動性と IRT のテーブル。

    行は tasks 起点（押下ゼロの習慣を消さない）。
    """
    if not tasks:
        return pd.DataFrame()

    windowed = hist[_iso_week(hist['date']).isin(weeks)] if not hist.empty else hist
    pressed = press_rows(windowed)

    rows = []
    for t in tasks:
        own = pressed[pressed['task_id'] == t['id']].sort_values('ts') if not pressed.empty else pressed
        n = len(own)
        if n >= VARIABILITY_MIN_POINTS:
            minutes = minutes_since_day_start(own['ts'])
            variability = f'{round(minutes.std())}分'
        else:
            variability = '-'
        if n >= 2:
            gaps = pd.to_datetime(own['ts']).diff().dropna().dt.total_seconds() / 86400
            irt_median = f'{gaps.median():.1f}日'
            irt_max = f'{gaps.max():.1f}日'
        else:
            irt_median = '-'
            irt_max = '-'
        rows.append((t.get('text', ''), n, variability, irt_median, irt_max))

    table = pd.DataFrame(rows, columns=['習慣', '点数', '時刻の変動性', 'IRT中央値', 'IRT最大'])
    table = table.set_index('習慣')
    return table


def coverage(weeks: list) -> pd.Series:
    """cron を走らせた日数。走らなかった日は「未達」ではなく欠測"""
    log = load_cron_log()
    if log.empty:
        return pd.Series({w: 0 for w in weeks})
    log = log.assign(week=_iso_week(log['date']))
    return log.groupby('week')['date'].nunique().reindex(weeks, fill_value=0)


def graduation_candidates(habits: list, dailys: list, value_min: float) -> list:
    """レビュー対象のものだけを候補にする。対象外の習慣は卒業もしない。

    **`track: down` の Habit は渡さない。** down の value は「押していない期間」で
    上がるが、押していない理由が「起きていない」か「押し忘れ」か区別できない。
    それを評価に使わないと決めておきながら卒業判定にだけ使うのは筋が通らない。
    しかも up/down 両方が立つ Habit は放置しても減衰しないので（実測: NoFap が
    660日で 8.18→8.995）、一度候補に出ると再発時にしか外れない。
    """
    rows = []
    for kind, group in (('habit', habits), ('daily', dailys)):
        for t in group:
            value = float(t.get('value', 0))
            if value >= value_min:
                rows.append((t.get('text', ''), kind, value))
    return sorted(rows, key=lambda r: -r[2])


def render_show(hist: pd.DataFrame, tasks: dict, config: dict, weeks: list,
                today: dt.date) -> str:
    roster = {k: (v or {}) for k, v in (config.get('habits') or {}).items()}
    grad = config.get('graduate') or {}
    done = graduated_ids(tasks)
    habits = [t for t in tasks.get('habits', []) if t['id'] not in done]
    dailys = [t for t in tasks.get('dailys', []) if t['id'] not in done]
    tracked = tracked_habits(roster, habits, 'up') + tracked_habits(roster, habits, 'down')
    picked_dailys = tracked_dailys(roster, dailys)
    tracked_ids = {t['id'] for t in tracked} | {t['id'] for t in picked_dailys}

    current = today.strftime('%G-W%V')
    labels = [f'{w} (途中)' if w == current else w for w in weeks]

    def relabel(table):
        return table.rename(columns=dict(zip(weeks, labels))) if not table.empty else table

    def section(title, table, note=None):
        body = [f'## {title}', '']
        body += [relabel(table).to_markdown() if not table.empty else '対象なし', '']
        if note:
            body += [note, '']
        return body

    out = [f'# 習慣レビュー {current}', '']

    absent = missing_from_habitica(roster, habits + dailys)
    if absent:
        out += ['> **対象に指定した習慣が Habitica にありません**: ' + ' / '.join(absent),
                '> リネームか削除。yaml を直すまでこの習慣はレビューされない。', '']

    out += section(
        'Habit / 増やす（週あたりの回数）',
        habit_table(hist, weeks, roster, habits, 'up'),
        '押した回数であって、やった回数ではない。**0 を「やらなかった」と読まない**。')
    out += section(
        'Habit / 減らす（週あたりの回数）',
        habit_table(hist, weeks, roster, habits, 'down'),
        '押し忘れると過少に出るうえ機械で裏が取れない。**評価の対象にしない**。')

    if tracked:
        out += ['## Habit / 最後に記録された日', '']
        for name, day, days in last_pressed(hist, tracked, today):
            when = f'{day}（{days}日前）' if day else '記録なし'
            out += [f'- {name}: {when}']
        out += ['', '窓の外の空白を見るための行。記録についての文で、'
                '「N日やっていない」とは読まない。', '']

    out += section(
        'Daily（完了 / due日数）', daily_table(hist, weeks, picked_dailys, roster),
        '目標がある習慣は「4週の平均が目標に届いたか」で見る。単週で判定しない。')

    out += section(
        '習慣のリズム（窓全体）', rhythm_table(hist, weeks, tracked + picked_dailys),
        '時刻の変動性は dayStart(5時) 起点の経過分。習慣化とは変動性の低下なので、'
        '回数が横ばいでも下がっていれば前進。IRT の最大は空白の長さだが、'
        'cron が走らなかった期間の欠測も含む。')

    cov = coverage(weeks)
    out += ['## 記録の被覆（cron を走らせた日数 / 7）', '',
            '| ' + ' | '.join(labels) + ' |',
            '|' + '---|' * len(weeks),
            '| ' + ' | '.join(f'{cov[w]}/7' for w in weeks) + ' |',
            '', 'Daily の分母はこの日数。走らなかった日は未達ではなく欠測。'
            ' (途中) の週は経過日数ぶんしか無いので、完了した週と比べない。', '']

    cands = graduation_candidates(tracked_habits(roster, habits, 'up'), picked_dailys,
                                  float(grad.get('value_min', 5)))
    out += ['## 卒業候補', '']
    if cands:
        out += [f'- {name}（{kind} / value {value:.1f}）' for name, kind, value in cands]
        out += ['', 'Tag「卒業」を付けて `repeat` を空にすると対象から外れる（手動）。']
    else:
        out += ['なし']

    untracked = [t.get('text', '') for t in habits + dailys if t['id'] not in tracked_ids]
    if untracked:
        out += ['', f'## 対象外（{len(untracked)}件）', '',
                '- ' + ' / '.join(untracked),
                '', 'Habitica には残っているがレビューしない。'
                '戻すには `config/habits.yaml` に足す。']

    if done:
        names = [t.get('text', '') for t in tasks.get('habits', []) + tasks.get('dailys', [])
                 if t['id'] in done]
        out += ['', f'## 卒業済み（{len(names)}件・対象外）', '',
                '\n'.join(f'- {n}' for n in sorted(names))]
    return '\n'.join(out) + '\n'


def cmd_show(args) -> int:
    hist = load_history()
    if hist.empty:
        print('history がありません。先に `habitica.py fetch` を実行してください',
              file=sys.stderr)
        return 1
    tasks = json.loads(TASKS_JSON.read_text()) if TASKS_JSON.exists() else {}
    today = dt.date.today()
    weeks = week_keys(today, args.weeks)
    config = load_config()
    print(render_show(hist, tasks, config, weeks, today), end='')

    # yaml が指す習慣が Habitica から消えていたら、レポートは出したうえで落とす。
    # 黙って対象から抜けるのが一番困る。
    absent = missing_from_habitica(config.get('habits') or {},
                                   tasks.get('habits', []) + tasks.get('dailys', []))
    if absent:
        print('対象に指定した習慣が Habitica にありません: ' + ' / '.join(absent),
              file=sys.stderr)
        return 1
    return 0


def cmd_status(_args) -> int:
    client = HabiticaClient.from_config(CREDS_FILE)
    user = client.get_user()
    stats = user.get('stats', {})
    prefs = user.get('preferences', {})
    print(f"lastCron   : {user.get('lastCron')}")
    print(f"needsCron  : {user.get('needsCron')}")
    print(f"dayStart   : {prefs.get('dayStart')}  timezoneOffset: {prefs.get('timezoneOffset')}")
    print(f"stats      : HP={stats.get('hp'):.1f} Lv{stats.get('lvl')} "
          f"exp={stats.get('exp')} gp={stats.get('gp'):.1f} class={stats.get('class')}")

    dailys = client.get_tasks('dailys')
    print(f"\nDailies ({len(dailys)}件)")
    for t in dailys:
        mark = '✔' if t.get('completed') else ('・' if t.get('isDue') else '-')
        print(f"  {mark} {t['text'][:24]:26} value={t['value']:>7.2f} "
              f"streak={t.get('streak', 0)} isDue={t.get('isDue')}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    parser = argparse.ArgumentParser(description='Habitica')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('cron', help='cron を確定させ、実行を記録する')
    sub.add_parser('fetch', help='Habit / Daily の history を CSV に落とす')
    p_show = sub.add_parser('show', help='週ごとの回数・達成をまとめて出す')
    p_show.add_argument('--weeks', type=int, default=4, help='さかのぼる週数（既定4）')
    sub.add_parser('status', help='現在の状態を表示する')
    args = parser.parse_args()

    handlers = {'cron': cmd_cron, 'fetch': cmd_fetch, 'show': cmd_show,
                'status': cmd_status}
    try:
        return handlers[args.command](args)
    except HabiticaError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
