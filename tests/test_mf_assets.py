"""
MF 資産推移（/bs/history/csv）のマージのテスト

MF が返す粒度は**当月だけ日次で、月をまたぐと月末1点に潰れる**。過去の日次は
MF 側から取り直せないため、マージが新データ側の粒度でCSVを上書きすると、
一度しか取れない日次が黙って消える（欠測の捏造）。ここを固定する。
"""

import io

import pandas as pd

from lib.mf import store

HEADER = ['日付', '合計（円）', '預金・現金（円）', '投資信託（円）']


def _csv(path, rows):
    pd.DataFrame(rows, columns=HEADER).to_csv(
        path, index=False, encoding=store.OUTPUT_ENCODING)


def _row(date, total, depo='0', fund='0'):
    return {'日付': date, '合計（円）': total,
            '預金・現金（円）': depo, '投資信託（円）': fund}


def test_save_assets_keeps_daily_rows_absent_from_new_data(tmp_path, monkeypatch):
    """月をまたいで取得した際、前月の日次行が月末1点で潰されない"""
    csv = tmp_path / '資産推移.csv'
    _csv(csv, [_row('2026/08/30', '100'), _row('2026/08/31', '110')])
    monkeypatch.setattr(store, 'ASSETS_CSV', csv)

    # 9月に入ってからの取得。8月は月末1点しか返らない
    store.save_assets(
        pd.DataFrame([_row('2026/08/31', '110'), _row('2026/09/01', '120')]),
        io.StringIO())

    saved = pd.read_csv(csv, encoding=store.OUTPUT_ENCODING, dtype=str)
    assert list(saved['日付']) == ['2026/08/30', '2026/08/31', '2026/09/01']


def test_save_assets_is_idempotent(tmp_path, monkeypatch):
    """同じ日を2回取っても行が増えない（日付がキー）"""
    csv = tmp_path / '資産推移.csv'
    monkeypatch.setattr(store, 'ASSETS_CSV', csv)
    df = pd.DataFrame([_row('2026/09/01', '120'), _row('2026/09/02', '130')])

    store.save_assets(df, io.StringIO())
    store.save_assets(df, io.StringIO())

    saved = pd.read_csv(csv, encoding=store.OUTPUT_ENCODING, dtype=str)
    assert len(saved) == 2


def test_save_assets_updates_same_day_value(tmp_path, monkeypatch):
    """同じ日を取り直したら新しい値で置き換わる（当日の残高は日中に動く）"""
    csv = tmp_path / '資産推移.csv'
    _csv(csv, [_row('2026/09/19', '100')])
    monkeypatch.setattr(store, 'ASSETS_CSV', csv)

    store.save_assets(pd.DataFrame([_row('2026/09/19', '200')]), io.StringIO())

    saved = pd.read_csv(csv, encoding=store.OUTPUT_ENCODING, dtype=str)
    assert list(saved['合計（円）']) == ['200']


def test_save_assets_keeps_existing_columns_when_category_disappears(tmp_path, monkeypatch):
    """保有区分が増減しても既存の列が落ちない（FX を解約した等）"""
    csv = tmp_path / '資産推移.csv'
    _csv(csv, [_row('2026/08/31', '110')])
    monkeypatch.setattr(store, 'ASSETS_CSV', csv)

    store.save_assets(
        pd.DataFrame([{'日付': '2026/09/01', '合計（円）': '120',
                       '預金・現金（円）': '0'}]),
        io.StringIO())

    saved = pd.read_csv(csv, encoding=store.OUTPUT_ENCODING, dtype=str)
    assert '投資信託（円）' in saved.columns
