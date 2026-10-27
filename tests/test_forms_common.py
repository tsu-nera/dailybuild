"""Google Forms の共通処理（src/lib/forms/）と汎用 forms.py fetch / show のテスト（ADR-002）

守るのは「欠測を捏造しないこと」「二重に入れないこと」。実 API は叩かず、
Forms の応答はフェイクにする。固有処理を持たないフォームが def yaml と
レジストリ1行だけで CSV と markdown を作れることもここで固定する。
"""

import argparse
import datetime as dt
import importlib.util
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib import forms_registry  # noqa: E402
from lib.clients import gforms_client  # noqa: E402
from lib.daily import store as daily_store  # noqa: E402
from lib.forms import defs, generic, schema  # noqa: E402
from lib.forms.responses import has_unfetched_responses, update_vocab_history  # noqa: E402


def _load_script(name):
    """scripts/ 配下はパッケージではないのでファイルから直接ロードする"""
    path = BASE_DIR / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


forms = _load_script('forms')
daily = _load_script('daily')


# --- update_vocab_history ---

def test_update_vocab_history_creates_file(tmp_path):
    path = tmp_path / 'emotion_vocab_history.csv'
    now = dt.datetime(2026, 8, 26, 10, 0, 0)
    changed = update_vocab_history('1', ['楽しい・うれしい', 'イライラ'], path, now=now)
    assert changed is True
    df = pd.read_csv(path, dtype=str)
    assert len(df) == 1
    assert df.iloc[0]['revision_id'] == '1'
    assert df.iloc[0]['labels'] == '楽しい・うれしい;イライラ'
    assert df.iloc[0]['first_seen'] == '2026-08-26 10:00:00'


def test_update_vocab_history_same_labels_no_append(tmp_path):
    path = tmp_path / 'emotion_vocab_history.csv'
    update_vocab_history('1', ['楽しい・うれしい'], path)
    changed = update_vocab_history('1', ['楽しい・うれしい'], path)
    assert changed is False
    assert len(pd.read_csv(path, dtype=str)) == 1


def test_update_vocab_history_new_revision_same_labels_no_append(tmp_path):
    """質問文の変更や setup-form --update の空打ちで revisionId だけが上がる。

    これで行が増えると「いつ語彙が変わったか」を知るのに labels を diff する
    羽目になり、このファイルの存在意義が消える（実機で発生: 00000008 -> 00000009）。
    """
    path = tmp_path / 'emotion_vocab_history.csv'
    update_vocab_history('00000008', ['楽しい・うれしい', 'イライラ'], path)
    changed = update_vocab_history('00000009', ['楽しい・うれしい', 'イライラ'], path)
    assert changed is False
    assert len(pd.read_csv(path, dtype=str)) == 1


def test_update_vocab_history_new_labels_append(tmp_path):
    path = tmp_path / 'emotion_vocab_history.csv'
    update_vocab_history('1', ['楽しい・うれしい'], path)
    changed = update_vocab_history('2', ['楽しい・うれしい', 'イライラ'], path)
    assert changed is True
    df = pd.read_csv(path, dtype=str)
    assert len(df) == 2
    assert df.iloc[0]['revision_id'] == '1'
    assert df.iloc[1]['revision_id'] == '2'
    # 旧語彙の行が残る（過去データの読み方が失われない）
    assert df.iloc[0]['labels'] == '楽しい・うれしい'


def test_update_vocab_history_label_order_change_is_a_change(tmp_path):
    """並び替えもフォームの見た目が変わる = 別の版として記録する"""
    path = tmp_path / 'emotion_vocab_history.csv'
    update_vocab_history('1', ['楽しい・うれしい', 'イライラ'], path)
    changed = update_vocab_history('2', ['イライラ', '楽しい・うれしい'], path)
    assert changed is True
    assert len(pd.read_csv(path, dtype=str)) == 2


def test_update_vocab_history_zero_padded_revision_survives_roundtrip(tmp_path):
    path = tmp_path / 'emotion_vocab_history.csv'
    update_vocab_history('00000004', ['楽しい・うれしい'], path)
    df = pd.read_csv(path, dtype=str)
    assert df.iloc[0]['revision_id'] == '00000004'
    changed = update_vocab_history('00000004', ['楽しい・うれしい'], path)
    assert changed is False


def test_update_vocab_history_records_labels_without_revision(tmp_path):
    """revisionId が取れなくても語彙は記録する（取りこぼしのほうが高くつく）"""
    path = tmp_path / 'emotion_vocab_history.csv'
    changed = update_vocab_history(None, ['楽しい・うれしい'], path)
    assert changed is True
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert df.iloc[0]['revision_id'] == ''
    assert df.iloc[0]['labels'] == '楽しい・うれしい'


# --- has_unfetched_responses（--allow-kind-replace の削除前ガード） ---
# 実際に1件失いかけたインシデントの再発防止（tests/test_emotion.py の
# cmd_setup_form のテストが、このガードを通ることを固定している）

def test_has_unfetched_responses_true_when_response_newer_than_csv():
    csv_max = pd.Timestamp('2026-08-31 15:01:00')
    responses = [{'lastSubmittedTime': '2026-08-31T06:05:00Z'}]  # JST 15:05
    assert has_unfetched_responses(responses, csv_max) is True


def test_has_unfetched_responses_false_when_no_response_newer_than_csv():
    csv_max = pd.Timestamp('2026-08-31 15:01:00')
    responses = [{'lastSubmittedTime': '2026-08-31T05:00:00Z'}]  # JST 14:00
    assert has_unfetched_responses(responses, csv_max) is False


def test_has_unfetched_responses_false_when_no_responses_at_all():
    assert has_unfetched_responses([], pd.Timestamp('2026-08-31 15:01:00')) is False


def test_has_unfetched_responses_true_when_csv_missing_but_responses_exist():
    """CSV がまだ無い（＝全件未取り込み）のに回答があるなら未取り込み扱い"""
    responses = [{'lastSubmittedTime': '2026-08-31T06:05:00Z'}]
    assert has_unfetched_responses(responses, None) is True


# --- defs: yaml の書き戻しはコメントを壊さない ---

def test_save_form_id_replaces_only_the_line(tmp_path):
    path = tmp_path / 'x_def.yaml'
    path.write_text('# 説明\nform_id:\nform_title: X  # 画面タイトル\n')
    defs.save_form_id(path, 'FORM1')
    assert path.read_text() == '# 説明\nform_id: FORM1\nform_title: X  # 画面タイトル\n'


def test_save_form_id_without_line_raises(tmp_path):
    path = tmp_path / 'x_def.yaml'
    path.write_text('form_title: X\n')
    with pytest.raises(ValueError, match='form_id'):
        defs.save_form_id(path, 'FORM1')


# --- 汎用 forms.py fetch / show（固有処理を持たない仮のフォーム） ---

# 固有処理を持たない仮のフォーム。グリッド2行・数値1問・自由記述1問
GENERIC_DEF = """\
# テスト用の仮のフォーム
form_id: FORM_X
form_title: 仮の記録
grid_title: いまの状態
score:
  low: 1
  high: 5
  low_label: 悪い
  high_label: 良い
questions:
  - key: energy
    label: 元気
    column: energy
    type: grid
    required: true
  - key: focus
    label: 集中
    column: focus
    type: grid
  - key: protein
    label: たんぱく質 (g)
    short: たんぱく質
    column: protein_g
    type: number
  - key: memo
    label: メモ
    column: memo
    type: text
"""


def _fake_form(conf):
    """schema.build_items と同じ並びの fake form（questionId は出現順の通し番号）"""
    items = []
    n = 0
    for title, entries in schema.grid_groups(conf):
        questions = []
        for e in entries:
            questions.append({'questionId': f'q{n}', 'rowQuestion': {'title': e['label']}})
            n += 1
        items.append({'title': title, 'questionGroupItem': {'questions': questions}})
    for e in schema.text_like_questions(conf):
        items.append({'title': e['label'], 'questionItem': {'question': {
            'questionId': f'q{n}', 'textQuestion': {}}}})
        n += 1
    return {'formId': conf['form_id'], 'revisionId': '1', 'items': items}


def _response(conf, form, submitted, **answers_by_key):
    by_title = gforms_client.question_id_by_title(form)
    label = {q['key']: q['label'] for q in conf['questions']}
    answers = {by_title[label[k]]: {'textAnswers': {'answers': [{'value': str(v)}]}}
               for k, v in answers_by_key.items()}
    return {'lastSubmittedTime': submitted, 'answers': answers}


def _utc(days_ago, hour_jst):
    """今日から days_ago 日前の JST hour_jst 時を UTC の RFC3339 で返す"""
    d = dt.date.today() - dt.timedelta(days=days_ago)
    t = dt.datetime.combine(d, dt.time(hour_jst)) - dt.timedelta(hours=9)
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


@pytest.fixture
def generic_env(tmp_path, monkeypatch):
    """tmp_path をリポジトリに見立て、仮のフォームをレジストリ1行で登録する"""
    load_forms = forms_registry.load_forms

    def setup(def_text, key='x'):
        (tmp_path / 'config').mkdir(exist_ok=True)
        (tmp_path / 'config' / f'{key}_def.yaml').write_text(def_text)
        registry = tmp_path / 'forms.yaml'
        registry.write_text(yaml.safe_dump({'forms': [{
            'key': key, 'name': '仮の記録', 'csv': f'data/{key}.csv', 'date_column': 'date',
            'status': 'active', 'cadence': 'daily', 'stale_after_days': None, 'note': '',
            'review': 'daily',
        }]}, allow_unicode=True))
        monkeypatch.setattr(generic, 'BASE_DIR', tmp_path)
        monkeypatch.setattr(forms_registry, 'load_forms', lambda: load_forms(registry))
        conf = yaml.safe_load(def_text)
        return conf, _fake_form(conf), tmp_path / 'data' / f'{key}.csv'
    return setup


def _serve(monkeypatch, form, responses):
    monkeypatch.setattr(gforms_client, 'create_service', lambda interactive=True: object())
    monkeypatch.setattr(gforms_client, 'get_form', lambda service, form_id: form)
    monkeypatch.setattr(gforms_client, 'list_responses', lambda service, form_id: responses)


def test_registry_without_fetch_show_uses_generic_commands(generic_env):
    generic_env(GENERIC_DEF)
    form = forms.forms_registry.load_forms()[0]
    assert form.generic_fetch and form.generic_show
    assert form.fetch == ('scripts/forms.py', 'fetch', 'x')


def test_generic_fetch_writes_csv_from_def_yaml_only(generic_env, monkeypatch):
    conf, form, csv = generic_env(GENERIC_DEF)
    _serve(monkeypatch, form, [
        _response(conf, form, _utc(1, 8), energy=4, protein=62.5, memo='朝食'),
        _response(conf, form, _utc(1, 21), energy=2),  # 同じ日の後の回答が採られる
        _response(conf, form, _utc(0, 9), energy=3, focus=5),
    ])

    assert forms.cmd_fetch(argparse.Namespace(key='x')) == 0

    df = pd.read_csv(csv)
    assert list(df.columns) == ['date', 'updated_at', 'energy', 'focus', 'protein_g', 'memo']
    assert len(df) == 2
    first = df.iloc[0]
    assert first['energy'] == 2
    # 後の回答で答えなかった項目は欠測（前の回答の値を混ぜない・0 で埋めない）
    assert pd.isna(first['focus']) and pd.isna(first['protein_g']) and pd.isna(first['memo'])
    assert df.iloc[1]['focus'] == 5
    history = pd.read_csv(csv.parent / 'x_grid_history.csv', dtype=str)
    assert history.iloc[0]['labels'] == '元気;集中'


def test_generic_fetch_twice_does_not_duplicate_rows(generic_env, monkeypatch):
    conf, form, csv = generic_env(GENERIC_DEF)
    _serve(monkeypatch, form, [_response(conf, form, _utc(1, 8), energy=4)])
    forms.cmd_fetch(argparse.Namespace(key='x'))
    before = pd.read_csv(csv)
    forms.cmd_fetch(argparse.Namespace(key='x'))
    pd.testing.assert_frame_equal(before, pd.read_csv(csv))


def test_generic_fetch_skips_form_before_setup(generic_env, monkeypatch):
    _, form, csv = generic_env(GENERIC_DEF.replace('form_id: FORM_X', 'form_id:'))
    _serve(monkeypatch, form, [])
    assert forms.cmd_fetch(argparse.Namespace(key='x')) == 0
    assert not csv.exists()


def test_generic_show_renders_markdown(generic_env, monkeypatch, capsys):
    conf, form, _ = generic_env(GENERIC_DEF)
    _serve(monkeypatch, form, [
        _response(conf, form, _utc(1, 8), energy=4, protein=62.5, memo='朝食'),
        _response(conf, form, _utc(0, 9), energy=3),
    ])
    forms.cmd_fetch(argparse.Namespace(key='x'))
    capsys.readouterr()

    assert forms.cmd_show(argparse.Namespace(key='x', review=None, days=7)) == 0

    out = capsys.readouterr().out
    assert out.startswith('# 仮の記録（')
    assert '記録 2日分（7日中）' in out
    assert '| 62.5 ' in out
    assert '朝食' in out
    assert '- たんぱく質: 1/7 (14%)' in out
    assert '- 集中: 0/7 (0%)' in out  # 未回答の日を分母から落とさない


def test_generic_show_by_review_runs_generic_form(generic_env, monkeypatch, capsys):
    conf, form, _ = generic_env(GENERIC_DEF)
    _serve(monkeypatch, form, [_response(conf, form, _utc(0, 9), energy=3)])
    forms.cmd_fetch(argparse.Namespace(key='x'))
    capsys.readouterr()
    assert forms.cmd_show(argparse.Namespace(key=None, review='daily', days=7)) == 0
    assert '# 仮の記録（' in capsys.readouterr().out


def test_generic_unit_response_keeps_every_response(generic_env, monkeypatch, capsys):
    """unit: response は同じ日の回答を潰さず、timestamp ごとに1行"""
    conf, form, csv = generic_env(GENERIC_DEF + 'unit: response\n')
    _serve(monkeypatch, form, [
        _response(conf, form, _utc(0, 8), energy=4),
        _response(conf, form, _utc(0, 21), energy=2),
    ])
    forms.cmd_fetch(argparse.Namespace(key='x'))

    df = pd.read_csv(csv)
    assert list(df.columns) == ['timestamp', 'date', 'energy', 'focus', 'protein_g', 'memo']
    assert df['energy'].tolist() == [4, 2]

    capsys.readouterr()
    forms.cmd_show(argparse.Namespace(key='x', review=None, days=7))
    out = capsys.readouterr().out
    assert '記録 2件 / 1日に記録あり（7日中）' in out
    assert '08:00' in out and '21:00' in out


def test_generic_retired_question_keeps_values_on_refetch(generic_env, monkeypatch):
    """退役（active: false）させた設問の過去値が、次の fetch の行置換で消えない"""
    conf, form, csv = generic_env(GENERIC_DEF)
    _serve(monkeypatch, form, [_response(conf, form, _utc(1, 8), energy=4, protein=60)])
    forms.cmd_fetch(argparse.Namespace(key='x'))

    retired = GENERIC_DEF.replace('    type: number\n', '    type: number\n    active: false\n')
    conf2, form2, _ = generic_env(retired)
    _serve(monkeypatch, form2, [_response(conf2, form2, _utc(1, 8), energy=4)])
    forms.cmd_fetch(argparse.Namespace(key='x'))

    df = pd.read_csv(csv)
    assert df.iloc[0]['protein_g'] == 60
    assert 'protein_g' in df.columns


def test_generic_setup_form_creates_form_and_backfills_question_ids(generic_env, monkeypatch):
    _, form, _ = generic_env(GENERIC_DEF.replace('form_id: FORM_X', 'form_id:'))
    def_file = generic.BASE_DIR / 'config' / 'x_def.yaml'
    monkeypatch.setattr(gforms_client, 'create_service', lambda: object())
    monkeypatch.setattr(gforms_client, 'create_form', lambda *a, **k: {'formId': 'NEW'})
    monkeypatch.setattr(gforms_client, 'sync_questions', lambda *a, **k: {})
    monkeypatch.setattr(gforms_client, 'get_form', lambda service, form_id: {**form, 'formId': 'NEW'})
    moved = []
    monkeypatch.setattr(forms.generic.cli, 'move_new_form_to_drive', moved.append)

    args = argparse.Namespace(key='x', update=False, allow_kind_replace=False)
    assert forms.cmd_setup_form(args) == 0

    conf = defs.load_def(def_file)
    assert conf['form_id'] == 'NEW'
    assert moved == ['NEW']  # 作成後に Drive の dailybuild フォルダへ移す
    by_key = {q['key']: q.get('question_id') for q in conf['questions']}
    assert by_key == {'energy': None, 'focus': None, 'protein': 'q2', 'memo': 'q3'}
    assert def_file.read_text().startswith('# テスト用の仮のフォーム\n')


def test_setup_form_refuses_form_with_its_own_script():
    args = argparse.Namespace(key='bowel', update=False, allow_kind_replace=False)
    assert forms.cmd_setup_form(args) == 2


# --- 日次記録はレジストリの汎用経路でも daily.py と同じ CSV になる ---

def test_daily_morning_generic_fetch_matches_daily_script(tmp_path, monkeypatch):
    conf = daily_store.load_def('morning')
    form = _fake_form(conf)
    responses = [
        _response(conf, form, _utc(2, 7), mind=4, body=3, comment='よく寝た'),
        _response(conf, form, _utc(1, 7), mind=2),
        _response(conf, form, _utc(1, 9), mind=3, sleep=4),
    ]
    _serve(monkeypatch, form, responses)

    by_script = tmp_path / 'by_script.csv'
    monkeypatch.setitem(daily_store.SLOTS['morning'], 'csv_file', by_script)
    monkeypatch.setitem(daily_store.SLOTS['morning'], 'grid_history_file',
                        tmp_path / 'by_script_history.csv')
    daily.cmd_fetch(argparse.Namespace(slot='morning', non_interactive=True))

    (tmp_path / 'config').mkdir()
    shutil.copy(daily_store.DEF_FILES['morning'], tmp_path / 'config' / 'daily_morning_def.yaml')
    monkeypatch.setattr(generic, 'BASE_DIR', tmp_path)
    assert forms.cmd_fetch(argparse.Namespace(key='daily_morning')) == 0

    by_registry = pd.read_csv(tmp_path / 'data' / 'daily_morning.csv')
    pd.testing.assert_frame_equal(pd.read_csv(by_script), by_registry)
    assert by_registry['source'].tolist() == ['form', 'form']
    assert by_registry['mind_score'].tolist() == [4, 3]
