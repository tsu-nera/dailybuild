#!/usr/bin/env python
# coding: utf-8
"""
ジャーナルの骨組み（数値・変化・欠測）を週ファイルへ追記する

journal スキルは対話の記録が主目的で、人がレビューを回さないと1行も残らない。
実際 2026-08-07 から3週間、うつエピソードで HRV が大きく動いた期間が丸ごと
空いた。記録が最も必要な状態が、記録が最も途切れやすい状態と一致している。

そこで数値の骨組みだけを機械が毎日書く。考察・Action Plan は従来どおり
`/journal` が対話のあとに追記する。骨組みは
`<!-- skeleton:start -->` 〜 `<!-- skeleton:end -->` に囲まれており、
再実行するとこの区間だけを差し替える。区間外に書かれた考察は保持する。

**マーカーを持たない既存エントリには一切触れない。** journal 移行前に人と
agent が書いた日次エントリ（2026-08-07 など）を機械が書き換えないため。

Usage:
    uv run scripts/journal_skeleton.py                 # 今日
    uv run scripts/journal_skeleton.py --date 2026-08-20
    uv run scripts/journal_skeleton.py --since 2026-08-10   # 範囲を遡って生成
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib.analytics.sleep.sleep_analysis import calc_sleep_timing  # noqa: E402
from lib.utils.private_data import ensure_dir, require_private_write  # noqa: E402

BASE_DIR = project_root
JOURNAL_DIR = BASE_DIR / 'reports' / 'journal'
INDEX_FILE = JOURNAL_DIR / 'JOURNAL.md'

WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']

START_MARKER = '<!-- skeleton:start -->'
END_MARKER = '<!-- skeleton:end -->'

# 毎日あるはずのソース。当日の行が無ければ欠測として出す。(ラベル, パス, 日付列)
DAILY_SOURCES = [
    ('sleep', 'data/fitbit/sleep.csv', 'dateOfSleep'),
    ('hrv', 'data/fitbit/hrv.csv', 'date'),
    ('rhr', 'data/fitbit/heart_rate.csv', 'date'),
    ('breathing_rate', 'data/fitbit/breathing_rate.csv', 'date'),
    ('activity', 'data/fitbit/activity.csv', 'date'),
    ('temperature_skin', 'data/fitbit/temperature_skin.csv', 'date'),
    ('manual', 'data/manual.csv', 'date'),
]

# 疎なソース。測る日と測らない日があるのが常態なので、当日の不在を欠測として
# 出さない。毎日「欠測」と書くと故障と未記録が同じ見た目になり、しかも毎日出る
# 警告は読み飛ばされる。代わりに最終記録からの経過日数を出し、判断は読み手に渡す。
# (ラベル, パス, 日付列, 表示名)
SPARSE_SOURCES = [
    ('temperature_core', 'data/fitbit/temperature_core.csv', 'date_time', '深部体温'),
    ('body_composition', 'data/healthplanet_innerscan.csv', 'date', '体組成'),
]


def _read(path, date_column):
    """CSV を日付 index の DataFrame として読む。無ければ空を返す"""
    full = BASE_DIR / path
    if not full.exists():
        return pd.DataFrame()
    df = pd.read_csv(full)
    if df.empty or date_column not in df.columns:
        return pd.DataFrame()
    df['_date'] = pd.to_datetime(df[date_column], errors='coerce').dt.normalize()
    return df.dropna(subset=['_date'])


def _sleep_timing(lo, hi):
    """入眠潜時・起床後臥床を sleep_levels.csv から求める

    sleep.csv の minutesToFallAsleep / minutesAfterWakeup は使えない。
    2026-05 の Google Health 移行以降ずっと 0 が入っており、実測値ではなく
    「埋まらなくなった列」になっている（移行前は非ゼロ）。0 をそのまま
    載せると起床後臥床が常にゼロだったことになり、起床困難の記録が消える。
    """
    df = _read('data/fitbit/sleep_levels.csv', 'dateOfSleep')
    if df.empty:
        return {}
    df = df[(df['_date'] >= lo) & (df['_date'] <= hi)]
    if df.empty:
        return {}
    return calc_sleep_timing(df)


def _main_sleep(df):
    """主睡眠だけに絞る。昼寝を睡眠時間として数えないため"""
    if df.empty or 'isMainSleep' not in df.columns:
        return df
    flag = df['isMainSleep'].astype(str).str.lower().isin(['true', '1'])
    return df[flag]


def collect_metrics(target: dt.date) -> list[dict]:
    """当日値・直近7日平均・前7日平均を指標ごとに集める"""
    ts = pd.Timestamp(target)
    recent = (ts - pd.Timedelta(days=6), ts)
    prior = (ts - pd.Timedelta(days=13), ts - pd.Timedelta(days=7))

    sleep = _main_sleep(_read('data/fitbit/sleep.csv', 'dateOfSleep'))
    if not sleep.empty:
        sleep = sleep.groupby('_date').first().reset_index()
    hrv = _read('data/fitbit/hrv.csv', 'date')
    rhr = _read('data/fitbit/heart_rate.csv', 'date')
    br = _read('data/fitbit/breathing_rate.csv', 'date')
    act = _read('data/fitbit/activity.csv', 'date')
    man = _read('data/manual.csv', 'date')
    # body レポートと同じ healthplanet_innerscan.csv を使う。体組成は3経路
    # （Fitbit / HealthPlanet / Google Health）あるが統合しない方針なので、
    # レポートと違う経路を読むと骨組みとレポートで数字が食い違う
    body = _read('data/healthplanet_innerscan.csv', 'date')

    timing = _sleep_timing(prior[0], ts)
    if timing:
        tdf = pd.DataFrame([
            {'_date': pd.to_datetime(k),
             'fall_asleep': v['minutes_to_fall_asleep'],
             'after_wake': v['minutes_after_wakeup']}
            for k, v in timing.items()
        ])
    else:
        tdf = pd.DataFrame()

    specs = [
        ('睡眠時間', sleep, lambda d: d['minutesAsleep'] / 60, 'h', 1),
        ('睡眠効率', sleep, lambda d: d['efficiency'], '%', 0),
        ('入眠潜時', tdf, lambda d: d['fall_asleep'], '分', 0),
        ('起床後臥床', tdf, lambda d: d['after_wake'], '分', 0),
        ('中途覚醒', sleep, lambda d: d['wakeCount'], '回', 0),
        ('HRV', hrv, lambda d: d['daily_rmssd'], 'ms', 1),
        ('RHR', rhr, lambda d: d['resting_heart_rate'], 'bpm', 0),
        ('BR', br, lambda d: d['breathing_rate'], '/min', 1),
        ('歩数', act, lambda d: d['steps'], '', 0),
        ('体重', body, lambda d: d['weight'], 'kg', 1),
        ('体脂肪率', body, lambda d: d['body_fat_rate'], '%', 1),
        ('主観 mind', man, lambda d: d['mind_score'], '', 1),
        ('主観 body', man, lambda d: d['body_score'], '', 1),
        ('主観 sleep', man, lambda d: d['sleep_score'], '', 1),
    ]

    rows = []
    for label, df, pick, unit, digits in specs:
        if df.empty:
            rows.append({'label': label, 'unit': unit, 'digits': digits,
                         'today': None, 'recent': None, 'prior': None})
            continue
        series = pd.to_numeric(pick(df), errors='coerce')
        series.index = df['_date'].values

        def window(lo, hi):
            w = series[(series.index >= lo) & (series.index <= hi)].dropna()
            return float(w.mean()) if len(w) else None

        today = series[series.index == ts].dropna()
        rows.append({
            'label': label, 'unit': unit, 'digits': digits,
            'today': float(today.iloc[0]) if len(today) else None,
            'recent': window(*recent),
            'prior': window(*prior),
        })
    return rows


def collect_missing(target: dt.date) -> list[str]:
    """毎日あるはずのソースのうち、当日の行が無いものを列挙する"""
    ts = pd.Timestamp(target)
    missing = []
    for label, path, col in DAILY_SOURCES:
        df = _read(path, col)
        if df.empty or not (df['_date'] == ts).any():
            missing.append(label)
    return missing


def collect_last_seen(target: dt.date) -> list[str]:
    """疎なソースの最終記録を「表示名 N日前（MM-DD）」で返す"""
    ts = pd.Timestamp(target)
    out = []
    for _label, path, col, name in SPARSE_SOURCES:
        df = _read(path, col)
        past = df[df['_date'] <= ts] if not df.empty else df
        if past.empty:
            out.append(f'{name} 記録なし')
            continue
        last = past['_date'].max()
        days = (ts - last).days
        when = last.strftime('%m-%d')
        out.append(f'{name} {"当日" if days == 0 else f"{days}日前"}（{when}）')
    return out


def collect_comment(target: dt.date) -> str | None:
    man = _read('data/manual.csv', 'date')
    if man.empty or 'comment' not in man.columns:
        return None
    row = man[man['_date'] == pd.Timestamp(target)]
    if row.empty:
        return None
    value = row.iloc[0]['comment']
    return None if pd.isna(value) else str(value).strip() or None


def _fmt(value, unit, digits):
    if value is None:
        return '-'
    return f'{value:,.{digits}f}{unit}'


def _fmt_delta(recent, prior, unit, digits):
    if recent is None or prior is None:
        return '-'
    return f'{recent - prior:+,.{digits}f}{unit}'


def render_skeleton(target: dt.date) -> str:
    metrics = collect_metrics(target)
    missing = collect_missing(target)
    comment = collect_comment(target)

    lines = [START_MARKER, '', '| 指標 | 当日 | 直近7日 | 前7日 | 変化 |',
             '|---|---|---|---|---|']
    for m in metrics:
        lines.append(
            f"| {m['label']} | {_fmt(m['today'], m['unit'], m['digits'])} "
            f"| {_fmt(m['recent'], m['unit'], m['digits'])} "
            f"| {_fmt(m['prior'], m['unit'], m['digits'])} "
            f"| {_fmt_delta(m['recent'], m['prior'], m['unit'], m['digits'])} |"
        )
    lines.append('')
    if comment:
        lines.append(f'**コメント（手動記録）**: {comment}')
        lines.append('')
    lines.append(f"**欠測**: {'、'.join(missing) if missing else 'なし'}")
    last_seen = collect_last_seen(target)
    if last_seen:
        lines.append('')
        lines.append(f"**最終記録（疎な指標）**: {'、'.join(last_seen)}")
    lines.append('')
    lines.append(END_MARKER)
    return '\n'.join(lines)


def week_file(target: dt.date) -> Path:
    iso = target.isocalendar()
    return JOURNAL_DIR / f'{iso.year}-W{iso.week:02d}.md'


def week_header(target: dt.date) -> str:
    iso = target.isocalendar()
    monday = target - dt.timedelta(days=iso.weekday - 1)
    sunday = monday + dt.timedelta(days=6)
    return (f'# {iso.year}-W{iso.week:02d} '
            f'({monday.strftime("%m/%d")} - {sunday.strftime("%m/%d")})')


def upsert_entry(target: dt.date) -> str:
    """週ファイルへ骨組みを追記/更新する。戻り値は行った操作"""
    path = require_private_write(week_file(target))
    ensure_dir(path.parent)

    heading = f'## {target.isoformat()} ({WEEKDAY_JA[target.weekday()]})'
    skeleton = render_skeleton(target)

    if not path.exists():
        path.write_text(f'{week_header(target)}\n\n{heading}\n\n{skeleton}\n',
                        encoding='utf-8')
        return 'created'

    text = path.read_text(encoding='utf-8')

    # 見出しは日付だけで探す（曜日表記の揺れに引きずられないため）
    pattern = re.compile(rf'^## {re.escape(target.isoformat())}\b.*$', re.MULTILINE)
    match = pattern.search(text)

    if match is None:
        # 日付順に差し込む。後ろにより新しい日付があればその手前へ
        insert_at = len(text)
        for m in re.finditer(r'^## (\d{4}-\d{2}-\d{2})\b.*$', text, re.MULTILINE):
            if m.group(1) > target.isoformat():
                insert_at = m.start()
                break
        body = f'{heading}\n\n{skeleton}\n\n'
        text = text[:insert_at].rstrip('\n') + '\n\n' + body + text[insert_at:].lstrip('\n')
        path.write_text(text.rstrip('\n') + '\n', encoding='utf-8')
        return 'inserted'

    # エントリの範囲を求める（次の ## まで）
    next_m = re.search(r'^## ', text[match.end():], re.MULTILINE)
    end = match.end() + (next_m.start() if next_m else len(text) - match.end())
    entry = text[match.start():end]

    if START_MARKER not in entry:
        # 人・agent が書いた既存エントリ。機械は触らない
        return 'skipped'

    new_entry = re.sub(
        rf'{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}',
        lambda _: skeleton, entry, count=1, flags=re.DOTALL)
    if new_entry == entry:
        return 'unchanged'
    path.write_text(text[:match.start()] + new_entry + text[end:], encoding='utf-8')
    return 'updated'


def ensure_index_row(target: dt.date) -> str:
    """索引に該当週の行が無ければ追加する。既存の要約は上書きしない"""
    path = require_private_write(INDEX_FILE)
    if not path.exists():
        return 'no-index'
    iso = target.isocalendar()
    name = f'{iso.year}-W{iso.week:02d}'
    text = path.read_text(encoding='utf-8')
    if f'[{name}]' in text:
        return 'exists'

    monday = target - dt.timedelta(days=iso.weekday - 1)
    sunday = monday + dt.timedelta(days=6)
    row = (f'| {monday.strftime("%m/%d")}-{sunday.strftime("%m/%d")} '
           f'| [{name}]({name}.md) | （骨組みのみ・要約未記入） |')

    # 索引は新しい順。常に先頭へ入れると古い週を後から足したとき順序が崩れる
    # （遡り生成で W33 → W34 の順に処理すると W34, W33, W35 と並ぶ）。
    # 自分より古い最初の週行の手前へ入れ、無ければ最後の週行の直後へ置く。
    # 月ファイルの行（YYYY-MM）は W パターンに掛からないので巻き込まない。
    weeks = list(re.finditer(r'^\|[^\n]*\[(\d{4}-W\d{2})\]\([^\n]*\n', text, re.MULTILINE))
    if weeks:
        older = next((m for m in weeks if m.group(1) < name), None)
        at = older.start() if older else weeks[-1].end()
        path.write_text(text[:at] + row + '\n' + text[at:], encoding='utf-8')
        return 'added'

    marker = re.search(r'^\|---\|---\|---\|\s*$', text, re.MULTILINE)
    if marker is None:
        return 'no-table'
    at = marker.end()
    path.write_text(text[:at] + '\n' + row + text[at:], encoding='utf-8')
    return 'added'


def main():
    parser = argparse.ArgumentParser(description='Journal skeleton writer')
    parser.add_argument('--date', type=dt.date.fromisoformat, default=None,
                        help='対象日（既定: 今日）')
    parser.add_argument('--since', type=dt.date.fromisoformat, default=None,
                        help='この日から --date までを遡って生成')
    args = parser.parse_args()

    end = args.date or dt.date.today()
    start = args.since or end
    if start > end:
        print(f'エラー: --since {start} が対象日 {end} より後', file=sys.stderr)
        return 1

    day = start
    while day <= end:
        action = upsert_entry(day)
        index = ensure_index_row(day)
        print(f'{day} {week_file(day).name}: {action} (index: {index})')
        day += dt.timedelta(days=1)
    return 0


if __name__ == '__main__':
    exit(main())
