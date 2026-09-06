# coding: utf-8
"""食事記録（Google Sheets → CSV）

書いているのは「欠測を捏造しないこと」「二重に入れないこと」「候補を絞り込む
規則が仕様どおりであること」の3点（ADR-002）。レポートの文面は対象にしない。
"""

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.food import store  # noqa: E402


def nutrient_frame(rows):
    """NUTRIENTS の一部だけ埋めた DataFrame を作るヘルパ"""
    df = pd.DataFrame(rows)
    for col in store.NUTRIENTS:
        if col not in df.columns:
            df[col] = 0.0
    return df


def test_sum_strictは未測定を0として足さない():
    df = nutrient_frame([
        {'energy_kcal': 100.0, 'protein_g': float('nan')},
        {'energy_kcal': 50.0, 'protein_g': 5.0},
    ])
    total = store._sum_strict(df, store.NUTRIENTS)
    assert total['energy_kcal'] == 150.0
    assert math.isnan(total['protein_g'])


def test_build_recipesは調理後総重量で割る():
    df_master = nutrient_frame([
        {'name': 'にんじん', 'energy_kcal': 40.0, 'protein_g': 1.0},
        {'name': '玉ねぎ', 'energy_kcal': 30.0, 'protein_g': 1.0},
    ])
    df_recipe = pd.DataFrame([
        {'recipe_name': 'カレー', 'cooked_total_g': 1000, 'name': 'にんじん', 'grams': 200},
        {'recipe_name': '', 'cooked_total_g': '', 'name': '玉ねぎ', 'grams': 300},
    ])
    recipes, unknown = store.build_recipes(df_recipe, df_master)
    assert unknown == []
    assert len(recipes) == 1
    # にんじん 200g→energy 80kcal、玉ねぎ 300g→energy 90kcal、合計170kcal
    # を調理後総重量1000gで割って100g換算 -> 17.0kcal/100g
    assert recipes.iloc[0]['energy_kcal'] == pytest.approx(17.0)
    assert recipes.iloc[0]['name'] == 'カレー'


def test_build_recipesはcooked_total_g未入力でエラー():
    df_master = nutrient_frame([{'name': 'にんじん', 'energy_kcal': 40.0}])
    df_recipe = pd.DataFrame([
        {'recipe_name': 'カレー', 'cooked_total_g': '', 'name': 'にんじん', 'grams': 200},
    ])
    with pytest.raises(ValueError):
        store.build_recipes(df_recipe, df_master)


def test_resolve_logは不正行を除外しつつ件数を報告する():
    df_foods = nutrient_frame([{'name': '鶏むね肉', 'energy_kcal': 100.0}])
    df_log = pd.DataFrame([
        {'date': '2026-09-01', 'meal': '昼', 'name': '鶏むね肉', 'grams': '150'},
        {'date': 'invalid-date', 'meal': '夜', 'name': '鶏むね肉', 'grams': '100'},
        {'date': '2026-09-02', 'meal': '朝', 'name': '鶏むね肉', 'grams': 'invalid'},
        {'date': '2026-09-03', 'meal': '朝', 'name': '', 'grams': '100'},
    ])
    entries, issues = store.resolve_log(df_log, df_foods)
    assert len(entries) == 1
    assert issues['bad_date'] == 1
    assert issues['bad_grams'] == 1
    assert issues['unknown_names'] == []


def test_resolve_logは未知の食品名を報告する():
    df_foods = nutrient_frame([{'name': '鶏むね肉', 'energy_kcal': 100.0}])
    df_log = pd.DataFrame([
        {'date': '2026-09-01', 'meal': '昼', 'name': '謎の冷凍食品', 'grams': '100'},
    ])
    entries, issues = store.resolve_log(df_log, df_foods)
    assert len(entries) == 1
    assert issues['unknown_names'] == ['謎の冷凍食品']
    assert math.isnan(entries.iloc[0]['energy_kcal'])


def test_aggregate_dailyは列名をレポート側の名前に変える():
    df_foods = nutrient_frame([{'name': '鶏むね肉', 'energy_kcal': 100.0}])
    df_log = pd.DataFrame([
        {'date': '2026-09-01', 'meal': '昼', 'name': '鶏むね肉', 'grams': '200'},
        {'date': '2026-09-01', 'meal': '夜', 'name': '鶏むね肉', 'grams': '100'},
    ])
    entries, _ = store.resolve_log(df_log, df_foods)
    daily = store.aggregate_daily(entries)
    assert daily.loc[pd.Timestamp('2026-09-01'), 'calories'] == pytest.approx(300.0)


def test_候補は実績上位とレシピと手動登録とseedの和集合():
    df_master = pd.DataFrame([
        {'name': '米', 'source': 'mext'},
        {'name': '解凍餃子', 'source': 'manual'},
    ])
    recipe_names = pd.Series(['カレー'])
    entry_names = pd.Series(['鶏むね肉', '鶏むね肉', '鶏むね肉', '豚肉', '豚肉', '牛肉'])
    names = store.select_candidates(
        df_master, recipe_names, entry_names, seed_names=['納豆'], top_n=2)
    # top_n=2 なので実績の中では 鶏むね肉・豚肉 だけが入り、牛肉は入らない
    assert names == sorted(['解凍餃子', 'カレー', '鶏むね肉', '豚肉', '納豆'])
    assert '米' not in names  # source=mext の全件は候補に含めない
    assert '牛肉' not in names


def test_候補selectはtop_nを超えて実績を採らない():
    df_master = pd.DataFrame(columns=['name', 'source'])
    entry_names = pd.Series([f'食品{i}' for i in range(10) for _ in range(10 - i)])
    names = store.select_candidates(
        df_master, [], entry_names, seed_names=[], top_n=3)
    assert len(names) == 3
    assert set(names) == {'食品0', '食品1', '食品2'}


def test_replace_csv_periodは新データに無い日付の既存行を消さない(tmp_path):
    from lib.utils import csv_utils

    csv_path = tmp_path / 'entries.csv'
    legacy = pd.DataFrame([
        {'date': '2026-08-19', 'meal': '昼', 'name': 'Cronometer由来', 'grams': 100},
    ])
    legacy.to_csv(csv_path, index=False)

    new = pd.DataFrame([
        {'date': '2026-09-01', 'meal': '昼', 'name': '鶏むね肉', 'grams': 200},
    ])
    merged = csv_utils.replace_csv_period(
        new, csv_path, date_column='date',
        start_date=new['date'].min(), end_date=new['date'].max(),
        sort_by=['date'])

    assert 'Cronometer由来' in list(merged['name'])
    assert '鶏むね肉' in list(merged['name'])
    assert len(merged) == 2


def test_同じシート内容で2回fetchしても行が増えない(tmp_path):
    from lib.utils import csv_utils

    csv_path = tmp_path / 'daily.csv'
    df_foods = nutrient_frame([{'name': '鶏むね肉', 'energy_kcal': 100.0}])
    df_log = pd.DataFrame([
        {'date': '2026-09-01', 'meal': '昼', 'name': '鶏むね肉', 'grams': '200'},
    ])
    entries, _ = store.resolve_log(df_log, df_foods)
    daily = store.aggregate_daily(entries).reset_index()
    daily['date'] = daily['date'].dt.strftime('%Y-%m-%d')

    for _ in range(2):
        merged = csv_utils.replace_csv_period(
            daily, csv_path, date_column='date',
            start_date=daily['date'].min(), end_date=daily['date'].max(),
            sort_by=['date'])
        merged.to_csv(csv_path, index=False)

    assert len(pd.read_csv(csv_path)) == 1


def test_シートが0件でも既存entriesが空なら故障扱いしない(tmp_path):
    csv_path = tmp_path / 'entries.csv'
    pd.DataFrame(columns=['date', 'name']).to_csv(csv_path, index=False)
    empty, _ = store.resolve_log(pd.DataFrame(), pd.DataFrame())
    assert store.detect_empty_sheet_failure(empty, csv_path) is False
    assert store.detect_empty_sheet_failure(empty, tmp_path / 'no-such.csv') is False


def test_シートが0件で既存entriesに行があれば故障扱いする(tmp_path):
    csv_path = tmp_path / 'entries.csv'
    pd.DataFrame([{'date': '2026-09-01', 'name': '鶏むね肉'}]).to_csv(csv_path, index=False)
    empty, _ = store.resolve_log(pd.DataFrame(), pd.DataFrame())
    assert store.detect_empty_sheet_failure(empty, csv_path) is True


def test_全件モードはレシピ名を含む():
    df_master = pd.DataFrame([
        {'name': '米', 'source': 'mext'},
        {'name': '解凍餃子', 'source': 'manual'},
    ])
    names = store.all_names(df_master, pd.Series(['カレー']), seed_names=['納豆'])
    # レシピ名が抜けると、鍋を登録してもドロップダウンから選べない
    assert names == sorted(['米', '解凍餃子', 'カレー', '納豆'])


def test_日付はシリアルでも文字列でも同じ日になる():
    # 「9/6」と入力するとシートは日付シリアルで保存し、表示だけ年を落とす。
    # 表示文字列を読むと 0001-09-06 になっていた
    parsed = store.parse_dates([46271, '2026-09-06', '', 'invalid'])
    assert parsed[0] == pd.Timestamp('2026-09-06')
    assert parsed[1] == pd.Timestamp('2026-09-06')
    assert pd.isna(parsed[2])
    assert pd.isna(parsed[3])


def test_resolve_logは日付シリアルを解釈する():
    df_foods = nutrient_frame([{'name': 'じゃがいも', 'energy_kcal': 51.0}])
    df_log = pd.DataFrame([
        {'date': 46271, 'meal': '', 'name': 'じゃがいも', 'grams': 240},
    ])
    entries, issues = store.resolve_log(df_log, df_foods)
    assert issues['bad_date'] == 0
    assert entries.iloc[0]['date'] == pd.Timestamp('2026-09-06')
    assert entries.iloc[0]['energy_kcal'] == pytest.approx(122.4)
