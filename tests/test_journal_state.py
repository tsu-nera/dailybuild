"""
STATE.md（現在の状態）の生成テスト

STATE.md は毎日全上書きされる生成物で、agent はこれを事実として読む。
壊れ方はどれも黙って進む種類:

1. 欠測日をストリークに数え、記録していないだけの日を「不調が続いた」に化けさせる
2. 未来日付の行（MF は引き落とし予定日の行を持つ）を最終記録として読み、
   パイプラインの遅れを実際より小さく見せる
3. 解決済みのアクションが未解決として残り続ける / 逆に未解決が落ちる
4. 追記になってしまい、再実行で状態が積み上がる

いずれも「例外を出さず正常終了する」ので、実行しても目視でも気づけない。
"""

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import journal_skeleton as js

TARGET = dt.date(2026, 9, 5)


def series(pairs):
    """(日, 値) から日付 index の Series を作る"""
    idx = pd.DatetimeIndex([pd.Timestamp(f'2026-09-{d:02d}') for d, _ in pairs])
    return pd.Series([v for _, v in pairs], index=idx, dtype=float)


def low(v):
    return v <= 1


# --- ストリークと欠測 ---------------------------------------------------

def test_counts_consecutive_days():
    s = series([(3, 1), (4, 1), (5, 1)])
    hit = js._streak(s, low, TARGET, include_today=True)
    assert hit['days'] == 3
    assert hit['gaps'] == 0
    assert hit['first'] == pd.Timestamp('2026-09-03')


def test_missing_start_does_not_begin_a_streak():
    """起点が欠測なら数え始めない。続いているかどうか分からないため"""
    s = series([(1, 1), (2, 1), (3, 1)])  # 09-04, 09-05 が無い
    assert js._streak(s, low, TARGET, include_today=True) is None


def test_gap_is_bridged_but_not_counted_as_a_hit():
    """穴は跨ぐが日数には数えない。数えると未記録が不調に化ける"""
    s = series([(2, 1), (3, 1), (5, 1)])  # 09-04 が欠測
    hit = js._streak(s, low, TARGET, include_today=True)
    assert hit['days'] == 3           # 09-05, 09-03, 09-02 の3日
    assert hit['gaps'] == 1           # 09-04 は穴として別に出す
    assert hit['span'] == 4           # 09-02〜09-05 の4日間にまたがる


def test_gap_longer_than_limit_truncates():
    """長い穴の向こう側は「続いていた」と言えないので繋がない"""
    s = series([(1, 1), (5, 1)])      # 09-02〜09-04 の3日が欠測
    assert js._streak(s, low, TARGET, include_today=True) is None


def test_trailing_gap_is_discarded():
    """末尾の穴で開始日が実在しない日にずれない"""
    s = series([(3, 1), (4, 1), (5, 1)])  # 09-02 は欠測（さらに手前も無い）
    hit = js._streak(s, low, TARGET, include_today=True)
    assert hit['first'] == pd.Timestamp('2026-09-03')
    assert hit['gaps'] == 0


def test_value_breaking_the_condition_stops_the_streak():
    s = series([(3, 1), (4, 5), (5, 1)])
    assert js._streak(s, low, TARGET, include_today=True) is None


def test_single_day_is_not_a_streak():
    s = series([(4, 5), (5, 1)])
    assert js._streak(s, low, TARGET, include_today=True) is None


def test_include_today_false_starts_from_yesterday():
    """歩数・陽性感情は当日が未確定。当日を数えると毎朝1日伸びる"""
    s = series([(3, 1), (4, 1), (5, 9)])   # 当日は条件を満たさない
    hit = js._streak(s, low, TARGET, include_today=False)
    assert hit['days'] == 2
    assert hit['through_today'] is False


# --- パイプラインの鮮度 -------------------------------------------------

def test_pipeline_ignores_future_dated_rows(tmp_path, monkeypatch):
    """MF は引き落とし予定日の行を持つ。未来日を最終記録に採ると遅れが消える"""
    csv = tmp_path / 'data' / 'mf.csv'
    csv.parent.mkdir(parents=True)
    csv.write_text('日付,金額\n2026-09-01,100\n2026-10-20,200\n', encoding='utf-8')

    monkeypatch.setattr(js, 'BASE_DIR', tmp_path)
    monkeypatch.setattr(js, 'PIPELINE_SOURCES',
                        [('MF', 'data/mf.csv', '日付', 4, 'active', '')])

    row = js.collect_pipeline(TARGET)[0]
    assert row['last'] == pd.Timestamp('2026-09-01')
    assert row['behind'] == 4


def test_degraded_source_still_reports_staleness(tmp_path, monkeypatch):
    """欠損ありでも鮮度は通常どおり見る。取得が完全に止まったのは別の異常"""
    csv = tmp_path / 'data' / 'mf.csv'
    csv.parent.mkdir(parents=True)
    csv.write_text('日付,金額\n2026-08-01,100\n', encoding='utf-8')

    monkeypatch.setattr(js, 'BASE_DIR', tmp_path)
    monkeypatch.setattr(js, 'PIPELINE_SOURCES',
                        [('MF', 'data/mf.csv', '日付', 4, 'degraded', '欠けている')])

    row = js.collect_pipeline(TARGET)[0]
    assert row['ok'] is False
    assert row['status'] == 'degraded'


def test_pipeline_reports_missing_source(tmp_path, monkeypatch):
    monkeypatch.setattr(js, 'BASE_DIR', tmp_path)
    monkeypatch.setattr(js, 'PIPELINE_SOURCES',
                        [('無い', 'data/none.csv', 'date', 1, 'active', '')])
    row = js.collect_pipeline(TARGET)[0]
    assert row['last'] is None and row['ok'] is False


# --- アクション台帳 -----------------------------------------------------

ACTIONS_SAMPLE = """# ACTIONS

| 発行日 | アクション | 状態 | 更新日 | 備考 |
|---|---|---|---|---|
| 2026-09-05 | 22時台に就寝する | 未達 | | メモ |
| 2026-09-04 | 体重計に乗る | 達成 | 2026-09-05 | |
| 2026-09-03 | 就寝を遅らせる | 撤回 | 2026-09-04 | 裏目 |
| 2026-09-02 | 記録を続ける | 継続 | | |
"""


@pytest.fixture
def actions_file(tmp_path, monkeypatch):
    path = tmp_path / 'ACTIONS.md'
    monkeypatch.setattr(js, 'ACTIONS_FILE', path)
    return path


def test_open_actions_drops_resolved_rows(actions_file):
    actions_file.write_text(ACTIONS_SAMPLE, encoding='utf-8')
    rows = js.collect_open_actions()
    assert [r['issued'] for r in rows] == ['2026-09-05', '2026-09-02']
    assert rows[0]['note'] == 'メモ'


def test_open_actions_ignores_header_and_prose(actions_file):
    """日付で始まらない行（見出し・説明文・区切り）を行として拾わない"""
    actions_file.write_text(
        ACTIONS_SAMPLE + '\n本文の| パイプを含む説明 |\n', encoding='utf-8')
    assert len(js.collect_open_actions()) == 2


def test_open_actions_without_file(actions_file):
    assert js.collect_open_actions() == []


def test_unknown_status_is_treated_as_open(actions_file):
    """知らない語を解決済みに倒すと、未解決が黙って消える"""
    actions_file.write_text(
        '| 発行日 | アクション | 状態 | 更新日 | 備考 |\n'
        '|---|---|---|---|---|\n'
        '| 2026-09-05 | なにか | 保留 | | |\n', encoding='utf-8')
    assert len(js.collect_open_actions()) == 1


# --- 生成物としての性質 -------------------------------------------------

def test_state_is_overwritten_not_appended(tmp_path, monkeypatch):
    path = tmp_path / 'STATE.md'
    monkeypatch.setattr(js, 'STATE_FILE', path)
    monkeypatch.setattr(js, 'render_state', lambda target: f'STATE {target}\n')

    js.write_state(TARGET)
    js.write_state(TARGET)
    assert path.read_text(encoding='utf-8') == 'STATE 2026-09-05\n'


def test_state_only_does_not_touch_week_files(tmp_path, monkeypatch):
    """--state-only で週ファイルを書き換えない（過去の考察を守る）"""
    monkeypatch.setattr(js, 'JOURNAL_DIR', tmp_path)
    monkeypatch.setattr(js, 'STATE_FILE', tmp_path / 'STATE.md')
    monkeypatch.setattr(js, 'render_state', lambda target: 'x\n')
    monkeypatch.setattr(sys, 'argv', ['journal_skeleton.py', '--state-only',
                                      '--date', '2026-09-05'])
    calls = []
    monkeypatch.setattr(js, 'upsert_entry', lambda d: calls.append(d))

    assert js.main() == 0
    assert calls == []


# --- ログの警告 ---------------------------------------------------------

def test_known_warnings_are_separated_from_new_ones(tmp_path, monkeypatch):
    """毎日出る警告と新規を同じ場所に並べると、新規が埋もれる"""
    log_dir = tmp_path / 'logs' / 'daily-routine'
    log_dir.mkdir(parents=True)
    (log_dir / '2026-09-05.log').write_text(
        '⚠️ 連携が正常でない口座が 9件。\n'
        '⚠️ 新しく起きたなにか\n'
        '=== Daily Routine Complete ===\n', encoding='utf-8')
    monkeypatch.setattr(js, 'BASE_DIR', tmp_path)

    run = js.collect_last_run()
    assert run['warnings'] == ['⚠️ 新しく起きたなにか']
    assert run['known_warnings'] == ['⚠️ 連携が正常でない口座が 9件。']
    assert run['complete'] is True
