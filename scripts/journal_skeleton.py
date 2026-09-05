#!/usr/bin/env python
# coding: utf-8
"""
ジャーナルの骨組み（数値・変化・欠測）を週ファイルへ追記する

journal スキルは対話の記録が主目的で、人がレビューを回さないと1行も残らない。
実際 2026-08-07 から3週間、うつエピソードで HRV が大きく動いた期間が丸ごと
空いた。記録が最も必要な状態が、記録が最も途切れやすい状態と一致している。

そこで数値の骨組みだけを機械が毎日書く。考察・Action Plan は journal スキルが
`<!-- review:start -->` 区間へ書き、機械はその不在を警告するだけ。骨組みは
`<!-- skeleton:start -->` 〜 `<!-- skeleton:end -->` に囲まれており、
再実行するとこの区間だけを差し替える。区間外に書かれた考察は保持する。

**マーカーを持たない既存エントリには一切触れない。** journal 移行前に人と
agent が書いた日次エントリ（2026-08-07 など）を機械が書き換えないため。

同時に `reports/journal/STATE.md` を全上書きで生成する。週ファイルが
「その日そう判断した」という**不変の経過**なのに対し、STATE.md は
「いま何がどうなっているか」という**揮発する現在値**で、性質が正反対のため
別ファイルに分けてある。ストリーク（連続日数）と鮮度は毎日計算し直せるので
agent に書かせない。書かせると毎日言い換えが発生して事実が漂流する。

Usage:
    uv run scripts/journal_skeleton.py                 # 今日
    uv run scripts/journal_skeleton.py --date 2026-08-20
    uv run scripts/journal_skeleton.py --since 2026-08-10   # 範囲を遡って生成
    uv run scripts/journal_skeleton.py --state-only    # STATE.md だけ作り直す
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib.analytics import sleep as sleep_lib  # noqa: E402
from lib.bowel.render import CATEGORY_BOUNDS  # noqa: E402
from lib.analytics.sleep.sleep_analysis import calc_sleep_timing  # noqa: E402
from lib.emotion import render as emotion_render  # noqa: E402
from lib.utils.private_data import ensure_dir, require_private_write  # noqa: E402

BASE_DIR = project_root
JOURNAL_DIR = BASE_DIR / 'reports' / 'journal'
INDEX_FILE = JOURNAL_DIR / 'JOURNAL.md'
STATE_FILE = JOURNAL_DIR / 'STATE.md'
ACTIONS_FILE = JOURNAL_DIR / 'ACTIONS.md'
EMOTION_DEF = BASE_DIR / 'config' / 'emotion_def.yaml'

WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']

START_MARKER = '<!-- skeleton:start -->'
END_MARKER = '<!-- skeleton:end -->'

# 散文側のマーカー。書くのは agent（journal スキル）で、機械は不在を検出するだけ。
REVIEW_MARKER = '<!-- review:start -->'
WEEKLY_MARKER = '<!-- weekly:start -->'

# 毎日あるはずのソース。当日の行が無ければ欠測として出す。(ラベル, パス, 日付列)
DAILY_SOURCES = [
    ('sleep', 'data/wearable/sleep.csv', 'dateOfSleep'),
    ('hrv', 'data/wearable/hrv.csv', 'date'),
    ('rhr', 'data/wearable/heart_rate.csv', 'date'),
    ('breathing_rate', 'data/wearable/breathing_rate.csv', 'date'),
    ('activity', 'data/wearable/activity.csv', 'date'),
    ('temperature_skin', 'data/wearable/temperature_skin.csv', 'date'),
    ('daily_summary', 'data/daily_summary.csv', 'date'),
]

# 疎なソース。測る日と測らない日があるのが常態なので、当日の不在を欠測として
# 出さない。毎日「欠測」と書くと故障と未記録が同じ見た目になり、しかも毎日出る
# 警告は読み飛ばされる。代わりに最終記録からの経過日数を出し、判断は読み手に渡す。
# (ラベル, パス, 日付列, 表示名)
SPARSE_SOURCES = [
    ('temperature_core', 'data/wearable/temperature_core.csv', 'date_time', '深部体温'),
    ('body_composition', 'data/healthplanet_innerscan.csv', 'date', '体組成'),
    # 排便は DAILY_SOURCES に入れない。記録の無い日が「未記録」なのか
    # 「出なかった」なのか原理的に判別できないため、当日の不在を欠測として
    # 毎日出すと故障と未記録が同じ見た目になる（SPARSE_SOURCES の趣旨）
    ('bowel', 'data/bowel.csv', 'date', '排便'),
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
    df = _read('data/wearable/sleep_levels.csv', 'dateOfSleep')
    if df.empty:
        return {}
    df = df[(df['_date'] >= lo) & (df['_date'] <= hi)]
    if df.empty:
        return {}
    return calc_sleep_timing(df)


def _sleep_debt_series(lo, hi):
    """lo〜hi の各日について睡眠負債(h)を返す

    レポートと同じ build_debt_calculator を使う。条件（必要睡眠 7.75h・14日窓・
    recency_linear）を片方だけ変えると、同じ日について2つの負債が出て
    どちらが正か分からなくなる。
    """
    df = _read('data/wearable/sleep.csv', 'dateOfSleep')
    if df.empty:
        return pd.DataFrame()
    calc = sleep_lib.build_debt_calculator(df)
    rows = []
    for day in pd.date_range(lo, hi, freq='D'):
        try:
            result = calc.calculate(end_date=day,
                                    weight_method=sleep_lib.DEBT_WEIGHT_METHOD)
        except ValueError:
            # 窓内のデータが min_data_points 未満。負債を出せない日は落とす
            continue
        rows.append({'_date': day, 'debt': result.sleep_debt_hours})
    return pd.DataFrame(rows)


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

    sleep = _main_sleep(_read('data/wearable/sleep.csv', 'dateOfSleep'))
    if not sleep.empty:
        sleep = sleep.groupby('_date').first().reset_index()
    hrv = _read('data/wearable/hrv.csv', 'date')
    rhr = _read('data/wearable/heart_rate.csv', 'date')
    br = _read('data/wearable/breathing_rate.csv', 'date')
    act = _read('data/wearable/activity.csv', 'date')
    man = _read('data/daily_summary.csv', 'date')
    # body レポートと同じ healthplanet_innerscan.csv を使う。体組成は3経路
    # （Fitbit / HealthPlanet / Google Health）あるが統合しない方針なので、
    # レポートと違う経路を読むと骨組みとレポートで数字が食い違う
    body = _read('data/healthplanet_innerscan.csv', 'date')
    debt = _sleep_debt_series(prior[0], ts)

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
        ('睡眠負債', debt, lambda d: d['debt'], 'h', 1),
        ('HRV', hrv, lambda d: d['daily_rmssd'], 'ms', 1),
        ('RHR', rhr, lambda d: d['resting_heart_rate'], 'bpm', 0),
        ('BR', br, lambda d: d['breathing_rate'], '/min', 1),
        ('歩数', act, lambda d: d['steps'], '', 0),
        ('体重', body, lambda d: d['weight'], 'kg', 1),
        ('体脂肪率', body, lambda d: d['body_fat_rate'], '%', 1),
        ('主観 mind', man, lambda d: d['mind_score'], '', 1),
        ('主観 body', man, lambda d: d['body_score'], '', 1),
        ('主観 head', man, lambda d: d['head_score'], '', 1),
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


def collect_bowel(target: dt.date) -> dict | None:
    """当日の排便記録と直近7日の内訳。記録が一度も無ければ None

    **平均は出さない。** ブリストルは 1〜7 の順序尺度で 4 が最良の U 字
    なので、型の平均は 1 と 7 の日を「理想的（4）」と書いてしまう。
    回数の日平均も出さない。記録の無い日を 0 とみなすと未記録と便秘が
    同じ値になり、欠測を捏造する（分母を記録のあった日に取り替えると
    今度はほぼ常に 1 以上になって情報が消える）。件数と日数をそのまま
    並べ、解釈は読み手に渡す。
    """
    df = _read('data/bowel.csv', 'date')
    if df.empty or 'bristol' not in df.columns:
        return None
    ts = pd.Timestamp(target)
    types = pd.to_numeric(df['bristol'], errors='coerce')

    today = types[df['_date'] == ts].dropna()
    window = types[(df['_date'] >= ts - pd.Timedelta(days=6))
                   & (df['_date'] <= ts)].dropna()
    days = df.loc[window.index, '_date'].nunique() if len(window) else 0

    return {
        'today': [int(v) for v in today],
        'today_rows': int((df['_date'] == ts).sum()),
        'week_count': int(len(window)),
        'week_days': days,
        'week_categories': {
            name: int(((window >= lo) & (window <= hi)).sum())
            for name, (lo, hi) in CATEGORY_BOUNDS.items()
        },
    }


def collect_comment(target: dt.date) -> str | None:
    man = _read('data/daily_summary.csv', 'date')
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


def _fmt_bowel(bowel: dict) -> str:
    """当日の型を並べ、直近7日は件数・日数・3分類の内訳を出す"""
    if bowel['today']:
        today = f"{bowel['today_rows']}回（型 {'、'.join(str(v) for v in bowel['today'])}）"
    elif bowel['today_rows']:
        # 送信はあったが型が読めない（未回答・パース不能）。0回と書かない
        today = f"{bowel['today_rows']}回（型 不明）"
    else:
        today = '記録なし'
    cats = '・'.join(f'{name}{n}' for name, n in bowel['week_categories'].items())
    return (f"当日 {today} / 直近7日 {bowel['week_count']}件・"
            f"{bowel['week_days']}日（{cats}）")


def render_skeleton(target: dt.date) -> str:
    metrics = collect_metrics(target)
    missing = collect_missing(target)
    comment = collect_comment(target)
    bowel = collect_bowel(target)

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
    if bowel:
        lines.append(f'**排便**: {_fmt_bowel(bowel)}')
        lines.append('')
    if comment:
        lines.append(f'**コメント（日次記録）**: {comment}')
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


def warn_unwritten(target: dt.date, weeks: int = 3) -> list[str]:
    """散文が書かれていない箇所を警告文のリストで返す（書き込みはしない）

    骨組みは毎日入るので、散文の不在は目視では気づけない。実際 W33-W36 は
    4週ぶん要約が空のまま埋もれた。日ごとの未記入はレビューを毎日回さない
    以上ふつうなので出さず、「レビューが止まっている」ことだけを出す。
    """
    warnings = []

    recent = [target - dt.timedelta(days=n) for n in range(7)]
    files = {week_file(d) for d in recent}
    if not any(REVIEW_MARKER in f.read_text(encoding='utf-8')
               for f in files if f.exists()):
        warnings.append('直近7日に review ブロックが無い（レビューが止まっている）')

    # 完了した週のみ。進行中の当週は未記入が正常
    monday = target - dt.timedelta(days=target.isocalendar().weekday - 1)
    for n in range(1, weeks + 1):
        day = monday - dt.timedelta(weeks=n)
        path = week_file(day)
        if not path.exists():
            continue
        if WEEKLY_MARKER not in path.read_text(encoding='utf-8'):
            warnings.append(f'{path.stem}: Weekly Summary が無い')

    return warnings


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


# ---------------------------------------------------------------------------
# STATE.md（現在の状態）
#
# 週ファイルは「その日そう判断した」という不変の経過で、追記しかしない。
# STATE.md はその逆で、毎回まるごと捨てて作り直す揮発した現在値。両者を
# 同じファイルに置くと、集約（毎日書き換わる）を追記の場所に置くことになり、
# agent が毎日 rollup を書き直す羽目になる。実際その運用で、事実が変わって
# いないのに表現だけが毎日漂流していた。
# ---------------------------------------------------------------------------

# ストリークを遡る上限。睡眠負債は1日ずつ計算するので伸ばすと比例して遅くなる
STREAK_LOOKBACK_DAYS = 60

# 欠測が何日続いたらストリークを打ち切るか。1〜2日の穴は取得の失敗でも起きる
# ので跨ぐが、それ以上は「続いていた」と言えない
STREAK_MAX_GAP = 2

# (表示名, 系列キー, 条件, 当日を数えるか)
#
# **ここで新しい判断を宣言しない。** 「6時間未満は問題」「3000歩未満は問題」は
# データの中の事実ではなく判断で、ここに書くと分析の方向をこの1箇所が固定する。
# 出してよいのは、**他所で既に宣言された判断**の持続だけ:
#
#   睡眠時間      daily-review スキルの観点「7-8時間が理想」
#   睡眠効率      同「85%以上が目標」
#   睡眠負債      config/targets.yaml（target 0 / direction zero）
#   主観スコア    config/daily_summary_def.yaml の score.low〜high "1-5"
#                 （下限=1。床に張り付いている状態を出す。「2以下」のような
#                 中間の線は引かない）
#   陽性感情      daily-review スキルの観点「陽性がN日途切れているは書く価値がある」
#
# 新しい条件を出したくなったら、先に宣言元（targets.yaml / スキルの観点）へ
# 書く。宣言は人が見る場所にあるので、方向の固定化が目に見える形でしか
# 起きない。境界値を変えるときも宣言元を直し、ここを合わせる。
#
# 当日を数えないものは、当日の値がまだ確定しない指標。陽性感情は「まだ記録して
# いないだけ」なので、当日を条件に入れると毎朝ストリークが1日伸びる。
STREAK_SPECS = [
    ('睡眠時間 < 7h', 'sleep_hours', lambda v: v < 7.0, True),
    ('睡眠効率 < 85%', 'sleep_efficiency', lambda v: v < 85, True),
    ('睡眠負債 > 0h', 'sleep_debt', lambda v: v > 0, True),
    ('主観 mind が下限(1)', 'mind', lambda v: v <= 1, True),
    ('主観 body が下限(1)', 'body', lambda v: v <= 1, True),
    ('主観 head が下限(1)', 'head', lambda v: v <= 1, True),
    ('主観 sleep が下限(1)', 'sleep_score', lambda v: v <= 1, True),
    ('陽性感情なし', 'positive', lambda v: v < 1, False),
]

# 取得パイプラインの鮮度。(表示名, パス, 日付列, 許容遅れ日数, 状態, 備考)
# パスの {year} は対象日の年で埋める（MF は年ごとにファイルが分かれる）。
#
# 状態の3分類。**「直さないと決めたもの」を要確認のまま置かない。** 毎日赤い行が
# あると表そのものが読み飛ばされるようになり、本当に新しい異常が埋もれる
# （SPARSE_SOURCES で疎な指標の不在を毎日「欠測」と書かないのと同じ理由）。
#   active   … 通常。遅れたら要確認
#   degraded … 取得は続くが構造的に不完全。鮮度は通常どおり評価しつつ、
#              欠損を常時注記する。取得が動いている分こちらの方が危険で、
#              欠けた数字を完全なものとして読まれる
#
# 運用をやめたソースはここから**行ごと消す**（`retired` のような状態は作らない）。
# 停止したものを毎日表に出しても、読み手にできることが何も無い。停止した事実と
# 理由は memory と CLAUDE.md が持つ。
PIPELINE_SOURCES = [
    ('Fitbit sleep', 'data/wearable/sleep.csv', 'dateOfSleep', 1, 'active', ''),
    ('Fitbit HRV', 'data/wearable/hrv.csv', 'date', 1, 'active', ''),
    ('Fitbit activity', 'data/wearable/activity.csv', 'date', 1, 'active', ''),
    ('日次記録', 'data/daily_summary.csv', 'date', 2, 'active', ''),
    ('体組成', 'data/healthplanet_innerscan.csv', 'date', 3, 'active',
     '測らない日があるのが常態'),
    ('気分記録', 'data/emotion.csv', 'date', 3, 'active', '断続で運用が成立している'),
    ('排便記録', 'data/bowel.csv', 'date', 4, 'active', '出ない日がある'),
    ('PHQ-9', 'data/phq9.csv', 'date', 8, 'active', '週次'),
    ('Toggl', 'data/toggl/time_entries.csv', 'start', 2, 'active', ''),
    ('MoneyForward', 'data/mf/収入・支出詳細_{year}.csv', '日付', 4, 'degraded',
     '連携が切れた口座の明細が入らない。**MF の集計は過少**。再認証しない方針'),
    ('Habitica', 'data/habitica/cron_log.csv', 'date', 1, 'active', ''),
]

# 毎日出る既知のログ警告。新規と同じ場所に並べると新規が埋もれるので分けて出す。
# 消さないのは、件数や範囲が変わったときに文言も変わるため（9件→15件は見える）。
KNOWN_LOG_WARNINGS = [
    '連携が正常でない口座が',
    'activityCalories / sedentaryMinutes',
    'メイン睡眠に重なる短いセッション',
    'push 対象期間',
]

# ACTIONS.md の状態欄。ここに無い語は「未解決」に倒す（見落とすより出しすぎる）
ACTION_CLOSED = {'達成', '撤回', '不要'}


def _valence_map() -> dict:
    """気分記録の label -> valence。読めなければ空 dict"""
    if not EMOTION_DEF.exists():
        return {}
    try:
        with open(EMOTION_DEF, encoding='utf-8') as f:
            conf = yaml.safe_load(f) or {}
    except yaml.YAMLError:
        return {}
    return emotion_render.valence_map(conf)


def _positive_series(lo, hi):
    """日ごとの陽性ラベル件数。記録の無い日は 0 で埋める（欠測ではない）

    「陽性が N 日途切れている」を数えるための系列なので、記録が無い日は
    陽性が無かった日として数えるのが正しい。

    emotion の show は streak を出さない方針（src/lib/emotion/render.py の
    docstring）。あれは**人が読む**出力で、不調期に折れると自己批判の材料に
    なるため。こちらは agent しか読まない状態ファイルで、daily-review が
    「陽性が N 日途切れている」を明示的に求めている。
    """
    idx = pd.date_range(lo, hi, freq='D')
    df = _read('data/emotion.csv', 'date')
    if df.empty or 'emotions' not in df.columns:
        return None
    vmap = _valence_map()
    if not vmap:
        # 極性が引けない状態で 0 埋めすると「陽性ゼロが60日continuing」に化ける
        return None
    hits = df[df['emotions'].apply(lambda e: emotion_render.has_positive(e, vmap))]
    counts = hits.groupby('_date').size() if not hits.empty else pd.Series(dtype=float)
    return counts.reindex(idx, fill_value=0).astype(float)


def _state_series(target: dt.date) -> dict:
    """ストリーク判定に使う日次系列を集める。値は日付 index の Series"""
    ts = pd.Timestamp(target)
    lo = ts - pd.Timedelta(days=STREAK_LOOKBACK_DAYS)
    out = {}

    def add(key, df, column, scale=1.0):
        if df.empty or column not in df.columns:
            return
        series = pd.to_numeric(df[column], errors='coerce') * scale
        series.index = pd.DatetimeIndex(df['_date'].values)
        series = series[(series.index >= lo) & (series.index <= ts)].dropna()
        if len(series):
            out[key] = series[~series.index.duplicated(keep='first')].sort_index()

    sleep = _main_sleep(_read('data/wearable/sleep.csv', 'dateOfSleep'))
    if not sleep.empty:
        sleep = sleep.groupby('_date').first().reset_index()
    add('sleep_hours', sleep, 'minutesAsleep', 1 / 60)
    add('sleep_efficiency', sleep, 'efficiency')

    man = _read('data/daily_summary.csv', 'date')
    add('mind', man, 'mind_score')
    add('body', man, 'body_score')
    add('head', man, 'head_score')
    add('sleep_score', man, 'sleep_score')

    add('sleep_debt', _sleep_debt_series(lo, ts), 'debt')

    positive = _positive_series(lo, ts)
    if positive is not None:
        out['positive'] = positive
    return out


def _streak(series, predicate, target: dt.date, include_today: bool) -> dict | None:
    """target から遡って条件が続いている日数を数える

    欠測の扱いが要点。起点が欠測なら数え始めない（続いているか分からない）。
    途中の穴は STREAK_MAX_GAP まで跨ぐが、日数には数えず gaps に出す。
    穴を「条件を満たした日」として数えると欠測を不調に化けさせる。
    末尾の穴は捨てる（開始日は必ず実データのある日になる）。
    """
    ts = pd.Timestamp(target)
    start = ts if include_today else ts - pd.Timedelta(days=1)
    limit = ts - pd.Timedelta(days=STREAK_LOOKBACK_DAYS)

    hits = []
    gaps = 0
    run_gap = 0
    cursor = start
    while cursor >= limit:
        if cursor in series.index:
            value = series.loc[cursor]
            if pd.isna(value) or not predicate(float(value)):
                break
            hits.append(cursor)
            gaps += run_gap          # 穴の手前にも該当日があったので中の穴として確定
            run_gap = 0
        else:
            if not hits:
                break
            run_gap += 1
            if run_gap > STREAK_MAX_GAP:
                break
        cursor -= pd.Timedelta(days=1)

    if len(hits) < 2:
        return None
    first = hits[-1]
    return {'days': len(hits), 'gaps': gaps, 'first': first,
            'span': (start - first).days + 1, 'through_today': include_today}


def collect_streaks(target: dt.date) -> list[dict]:
    """継続中のストリークを長い順に返す"""
    series = _state_series(target)
    out = []
    for label, key, predicate, include_today in STREAK_SPECS:
        if key not in series:
            continue
        hit = _streak(series[key], predicate, target, include_today)
        if hit:
            out.append({'label': label, **hit})
    return sorted(out, key=lambda r: r['days'], reverse=True)


def collect_pipeline(target: dt.date) -> list[dict]:
    """各ソースの最終行と遅れ日数。未来日は当日で切る（MF は未来明細を持つ）"""
    ts = pd.Timestamp(target)
    rows = []
    for name, path, column, tolerance, status, note in PIPELINE_SOURCES:
        df = _read(path.format(year=target.year), column)
        past = df[df['_date'] <= ts] if not df.empty else df
        if past.empty:
            rows.append({'name': name, 'last': None, 'behind': None,
                         'ok': False, 'status': status, 'note': note})
            continue
        last = past['_date'].max()
        behind = (ts - last).days
        rows.append({'name': name, 'last': last, 'behind': behind,
                     'ok': behind <= tolerance, 'status': status, 'note': note})
    return rows


def collect_last_run() -> dict | None:
    """最後の daily-routine.sh 実行のログから、完了と失敗ステップと警告を拾う

    ログの書式に依存するのはこの3つだけにしてある（完了マーカー・失敗行・
    警告行）。いずれも daily-routine.sh と各スクリプトが固定文字列で出す。
    """
    log_dir = BASE_DIR / 'logs' / 'daily-routine'
    logs = sorted(log_dir.glob('*.log')) if log_dir.is_dir() else []
    if not logs:
        return None
    latest = logs[-1]
    text = latest.read_text(encoding='utf-8', errors='replace')
    failed = re.findall(r'^=== 失敗した取得: (.+) ===$', text, re.MULTILINE)
    fresh, known = [], []
    for line in re.findall(r'^\s*[⚠!].*$', text, re.MULTILINE):
        line = line.strip()
        if not line:
            continue
        bucket = known if any(k in line for k in KNOWN_LOG_WARNINGS) else fresh
        if line not in bucket:
            bucket.append(line)
    return {
        'date': latest.stem,
        'complete': '=== Daily Routine Complete ===' in text,
        'failed': failed[-1] if failed else None,
        'warnings': fresh[:6],
        'known_warnings': known[:6],
    }


def collect_open_actions() -> list[dict]:
    """ACTIONS.md の未解決行。ファイルが無ければ空

    台帳を別ファイルにしてあるのは、書き込みを1行に局所化するため。
    日次 review の散文に埋めると「何を出して、どうなったか」を引くのに
    週ファイル全体を読み直すことになる（実際そうなっていた）。
    """
    if not ACTIONS_FILE.exists():
        return []
    rows = []
    for line in ACTIONS_FILE.read_text(encoding='utf-8').splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 3 or set(cells[0]) <= set('- :'):
            continue
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', cells[0]):
            continue
        if cells[2] in ACTION_CLOSED:
            continue
        rows.append({'issued': cells[0], 'action': cells[1], 'status': cells[2],
                     'note': cells[4] if len(cells) > 4 else ''})
    return rows


def _fmt_streak(row: dict) -> str:
    when = row['first'].strftime('%m-%d')
    body = f"{row['days']}日（{when}〜"
    body += '当日' if row['through_today'] else '前日'
    body += '）'
    if row['gaps']:
        body += f" ※欠測{row['gaps']}日を挟む"
    return body


def render_state(target: dt.date) -> str:
    """STATE.md の全文。生成物なので毎回まるごと差し替える"""
    lines = [
        '# STATE',
        '',
        '**生成物。手で編集しない**（`scripts/journal_skeleton.py` が毎日全上書きする）。',
        'ここは「いま何がどうなっているか」だけを持つ。「その日そう判断した」という',
        '経過は週ファイル（`YYYY-Wxx.md`）、来月も真な事実は memory に置く。',
        '',
        f'- 対象日: {target.isoformat()} ({WEEKDAY_JA[target.weekday()]})',
        '',
        '## 現在値',
        '',
        '| 指標 | 当日 | 直近7日 | 前7日 | 変化 |',
        '|---|---|---|---|---|',
    ]
    for m in collect_metrics(target):
        lines.append(
            f"| {m['label']} | {_fmt(m['today'], m['unit'], m['digits'])} "
            f"| {_fmt(m['recent'], m['unit'], m['digits'])} "
            f"| {_fmt(m['prior'], m['unit'], m['digits'])} "
            f"| {_fmt_delta(m['recent'], m['prior'], m['unit'], m['digits'])} |"
        )

    lines += ['', '## 継続中のストリーク', '']
    streaks = collect_streaks(target)
    if streaks:
        lines += ['| 条件 | 継続 |', '|---|---|']
        lines += [f"| {r['label']} | {_fmt_streak(r)} |" for r in streaks]
        lines += ['', '> 2日以上のものだけ。陽性感情は当日が未確定なので前日まで。',
                  '> **日数はレビュー本文に書かない。**データの訂正で後から変わるので、不変の記録に残すと嘘になる。']
    else:
        lines.append('継続中のものは無い（2日以上）。')

    lines += ['', '## 最終記録（疎な指標）', '']
    lines.append('、'.join(collect_last_seen(target)) or '-')

    lines += ['', '## 未解決のアクション', '']
    actions = collect_open_actions()
    if actions:
        lines += ['| 発行日 | アクション | 状態 | 備考 |', '|---|---|---|---|']
        lines += [f"| {a['issued']} | {a['action']} | {a['status']} | {a['note']} |"
                  for a in actions]
        lines += ['', f'> 全履歴は [ACTIONS.md]({ACTIONS_FILE.name})。']
    else:
        lines.append(f'なし（台帳: [ACTIONS.md]({ACTIONS_FILE.name})）。')

    lines += ['', '## パイプライン', '',
              '| ソース | 最終 | 遅れ | 判定 | 備考 |', '|---|---|---|---|---|']
    for row in collect_pipeline(target):
        if row['status'] == 'degraded':
            verdict = '欠損あり' if row['ok'] else '欠損あり・要確認'
        else:
            verdict = 'OK' if row['ok'] else '要確認'
        if row['last'] is None:
            lines.append(f"| {row['name']} | - | - | {verdict} | データなし |")
            continue
        lines.append(
            f"| {row['name']} | {row['last'].strftime('%m-%d')} | {row['behind']}日 "
            f"| {verdict} | {row['note']} |")
    lines += ['', '> `欠損あり` は取得が動いているのにデータが構造的に欠けているもので、'
                  '**数値をそのまま読むと過少になる**。']

    run = collect_last_run()
    if run:
        lines += ['', f"**最終実行**: {run['date']} "
                      f"({'完了' if run['complete'] else '未完了'})"]
        if run['failed']:
            lines.append(f"**失敗ステップ**: {run['failed']}")
        if run['warnings']:
            lines += ['', '**ログの警告（新規）**:']
            lines += [f'- {w}' for w in run['warnings']]
        if run['known_warnings']:
            lines += ['', '**ログの警告（既知・毎日出る）**:']
            lines += [f'- {w}' for w in run['known_warnings']]

    lines += ['', *[f'⚠️ {w}' for w in warn_unwritten(target)]]
    return '\n'.join(lines).rstrip('\n') + '\n'


def write_state(target: dt.date) -> str:
    path = require_private_write(STATE_FILE)
    ensure_dir(path.parent)
    path.write_text(render_state(target), encoding='utf-8')
    return str(path)


def main():
    parser = argparse.ArgumentParser(description='Journal skeleton writer')
    parser.add_argument('--date', type=dt.date.fromisoformat, default=None,
                        help='対象日（既定: 今日）')
    parser.add_argument('--since', type=dt.date.fromisoformat, default=None,
                        help='この日から --date までを遡って生成')
    parser.add_argument('--state-only', action='store_true',
                        help='週ファイルに触らず STATE.md だけ作り直す')
    args = parser.parse_args()

    end = args.date or dt.date.today()
    start = args.since or end
    if start > end:
        print(f'エラー: --since {start} が対象日 {end} より後', file=sys.stderr)
        return 1

    if not args.state_only:
        day = start
        while day <= end:
            action = upsert_entry(day)
            index = ensure_index_row(day)
            print(f'{day} {week_file(day).name}: {action} (index: {index})')
            day += dt.timedelta(days=1)

    # STATE.md は生成物なので毎回まるごと差し替える。遡り生成でも「いまの状態」は
    # 1つしか無いので、対象日ではなく最終日ぶんだけを書く
    print(f'STATE: {write_state(end)}')

    for w in warn_unwritten(end):
        print(f'\u26a0\ufe0f {w}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    exit(main())
