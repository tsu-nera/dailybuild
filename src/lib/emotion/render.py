"""
気分記録の markdown 出力

pandas 以外の外部依存を持たない。CSV の読み込みは store.py が担う。

語彙の極性（valence）は config/emotion_def.yaml が持つので、呼び出し側から
辞書で受け取る（lib 側から config を読まない）。過去の語彙版で記録された語は
現在の定義に無いことがあるため、極性が引けない語も集計から落とさず
「不明」として数える（data/emotion_vocab_history.csv が版を持っている）。

出さないものを明示しておく。いずれも履歴上わかっている落とし穴:
- 語 → 数値の変換（陽性=+1 等）。重みが恣意的で score の劣化版になる
- 主観と客観（HRV 等）の乖離判定。rho≈-0.00 で乖離が常態なので毎日出しても情報がない
- streak・記録率の達成度。不調期に折れると自己批判の材料になる
"""

import datetime as dt

import pandas as pd

from lib.emotion import store

WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']

VALENCE_JA = {'pos': '陽性', 'neg': '陰性', 'neu': '中立'}
VALENCE_UNKNOWN = '不明'


def valence_map(conf: dict) -> dict:
    """yaml の vocabulary から label -> valence の辞書を作る"""
    return {v['label']: v.get('valence') for v in conf.get('vocabulary', [])}


def has_positive(emotions, vmap: dict) -> bool:
    """陽性ラベルを1つ以上含むか。極性が引けない語は陽性に数えない"""
    return any(vmap.get(label) == 'pos' for label in store.split_labels(emotions))


def _day_label(ts) -> str:
    return f"{ts.strftime('%m-%d')} ({WEEKDAY_JA[ts.weekday()]})"


def _score_str(value) -> str:
    return '-' if pd.isna(value) else str(int(value))


def render_entries(df: pd.DataFrame) -> str:
    """記録の素の一覧。集計せず時刻順に並べる"""
    if df.empty:
        return '（この期間に記録がありません）'
    out = pd.DataFrame({
        '日': [_day_label(t) for t in df['timestamp']],
        '時刻': [t.strftime('%H:%M') for t in df['timestamp']],
        '気分': [_score_str(v) for v in df['score']],
        '気持ち': [' / '.join(store.split_labels(e)) for e in df['emotions']],
        'メモ': list(df['note']),
    })
    return out.to_markdown(index=False)


def render_intraday(df: pd.DataFrame) -> str:
    """同じ日に score つきの記録が2件以上ある日の、最初と最後の差

    抑うつ状態では1日の中の変化が記憶に残らないので、差そのものを出す。
    良し悪しの解釈は付けない。
    """
    scored = df[df['score'].notna()]
    rows = []
    for date, group in scored.groupby(scored['timestamp'].dt.normalize()):
        if len(group) < 2:
            continue
        first, last = group.iloc[0], group.iloc[-1]
        diff = int(last['score']) - int(first['score'])
        rows.append({
            '日': _day_label(date),
            '最初': f"{first['timestamp']:%H:%M} ({int(first['score'])})",
            '最後': f"{last['timestamp']:%H:%M} ({int(last['score'])})",
            '差': f'{diff:+d}' if diff else '±0',
        })
    if not rows:
        return '（同じ日に score つきの記録が2件以上ある日がない）'
    return pd.DataFrame(rows).to_markdown(index=False)


def render_positive(df: pd.DataFrame, df_all: pd.DataFrame, vmap: dict,
                    today: dt.date) -> str:
    """陽性感情の頻度と最終出現

    config/emotion_def.yaml が語彙を陽性に寄せている通り、回復の計器になるのは
    陰性の量ではなく陽性の頻度。最終出現は期間外まで遡って探す（期間内に
    1件も無いとき「いつ以来か」が最も知りたい情報になるため）。
    """
    lines = []
    if df.empty:
        lines.append('- 期間内: 記録なし')
    else:
        n_pos = sum(has_positive(e, vmap) for e in df['emotions'])
        pct = round(100 * n_pos / len(df))
        lines.append(f'- 期間内: {len(df)}件中 **{n_pos}件** に陽性のラベル（{pct}%）')

    positives = df_all[[has_positive(e, vmap) for e in df_all['emotions']]]
    if positives.empty:
        lines.append('- 最終出現: 記録開始以降なし')
    else:
        last = positives.iloc[-1]
        ago = (today - last['timestamp'].date()).days
        ago_str = '今日' if ago == 0 else f'{ago}日前'
        labels = ' / '.join(label for label in store.split_labels(last['emotions'])
                            if vmap.get(label) == 'pos')
        lines.append(f"- 最終出現: **{last['timestamp']:%m-%d %H:%M}**"
                     f"「{labels}」（{ago_str}）")
    return '\n'.join(lines)


def render_vocab(df: pd.DataFrame, vmap: dict) -> str:
    """語の出現回数（生カウント）

    12語を意味のある頻度で埋めるには数値記録の10倍以上の n が要るので、
    当面は参考値。割合や重み付けはしない。
    """
    labels = [label for e in df['emotions'] for label in store.split_labels(e)]
    if not labels:
        return '（記録なし）'
    counts = pd.Series(labels).value_counts()
    out = pd.DataFrame({
        '気持ち': list(counts.index),
        '極性': [VALENCE_JA.get(vmap.get(label), VALENCE_UNKNOWN)
                 for label in counts.index],
        '回数': list(counts.values),
    })
    return out.to_markdown(index=False)
