"""
meditation.build_eval() の種類ごとのまとめ。種類・表示名・目安は satoru の config/meditation_types.yaml が正本
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib import meditation

TYPES_YAML = """\
samatha:
  label: サマタ
  target: 20
vipassana:
  label: ヴィパッサナー
metta:
  label: メッター
"""


def _session(kind, reject=5.0):
    return {'meditation_type': kind, 'focus_rating': 3.0, 'drowsiness_rating': 2.0,
            'tp_alpha_db_change': -0.5, 'tp_delta_db_change': -2.0, 'artifact_reject_pct': reject}


def test_load_types_keeps_order_and_missing_target(tmp_path):
    path = tmp_path / 'meditation_types.yaml'
    path.write_text(TYPES_YAML, encoding='utf-8')
    types = meditation.load_types(path)
    assert list(types) == ['samatha', 'vipassana', 'metta']
    assert types['samatha'] == {'label': 'サマタ', 'target': 20}
    assert types['metta']['target'] is None


def test_types_without_target_appear_only_when_practiced(tmp_path):
    path = tmp_path / 'meditation_types.yaml'
    path.write_text(TYPES_YAML, encoding='utf-8')
    rows = meditation.build_eval([_session('metta'), _session('samatha', reject=50.0)], meditation.load_types(path))
    by_kind = {r['meditation_type']: r for r in rows}
    assert list(by_kind) == ['samatha', 'metta']  # vipassana は0回かつ目安なしなので出さない
    assert by_kind['samatha']['n'] == 1 and by_kind['samatha']['n_dropped'] == 1
    assert by_kind['samatha']['tp_alpha_db_change_median'] is None
    assert by_kind['metta'] == {**by_kind['metta'], 'label': 'メッター', 'target': None, 'n': 1,
                                'tp_alpha_db_change_median': -0.5}
