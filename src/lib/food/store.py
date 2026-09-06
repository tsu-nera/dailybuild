#!/usr/bin/env python
# coding: utf-8
"""
食事記録の読み取りと栄養計算

入力は Google Sheets の3シート（config/food_def.yaml の tabs）:

  food_master  スクリプトが書く。食品名の一覧（ドロップダウンの参照範囲）
  food_recipe  人が書く。鍋の材料。recipe_name と cooked_total_g は
               最初の材料行にだけ書けばよく、以降の空欄は上から埋める
  food_log     人が書く。date / meal / name / grams

name は食品マスタの食品名かレシピ名。成分表の食品名は2,538件すべて一意なので
名前をそのまま主キーにできる。

欠測（成分表の「-」＝未測定）は NaN のまま伝播させる。合算で 0 として
足し込むと、測っていない成分を「摂っていない」と偽ることになるため。
"""

from pathlib import Path

import gspread
import pandas as pd

from lib.utils.private_data import require_private_path

from . import mext

BASE_DIR = Path(__file__).resolve().parents[3]
NUTRITION_DIR = BASE_DIR / 'data' / 'nutrition'

# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
MASTER_CSV = require_private_path(NUTRITION_DIR / 'foods_master.csv')
RECIPES_CSV = require_private_path(NUTRITION_DIR / 'recipes.csv')
ENTRIES_CSV = require_private_path(NUTRITION_DIR / 'entries.csv')
DAILY_CSV = require_private_path(NUTRITION_DIR / 'daily.csv')

NUTRIENTS = list(mext.COMPONENTS.values())

# レポート側（templates/, src/lib/analytics/nutrition.py）が読む列名。
# 既存の data/wearable/nutrition.csv と揃えて無改修で差し替えられるようにする
REPORT_ALIASES = {
    'energy_kcal': 'calories',
    'carb_g': 'carbs',
    'fat_g': 'fat',
    'fiber_g': 'fiber',
    'protein_g': 'protein',
    'sodium_mg': 'sodium',
    'water_g': 'water',
}

MASTER_SHEET = 'food_master'
RECIPE_SHEET = 'food_recipe'
LOG_SHEET = 'food_log'

RECIPE_COLUMNS = ['recipe_name', 'cooked_total_g', 'name', 'grams']
LOG_COLUMNS = ['date', 'meal', 'name', 'grams', 'note']


def _sum_strict(df, columns):
    """
    成分ごとに合計する。ひとつでも未測定があればその成分は NaN にする。

    pandas の sum は既定で NaN を飛ばすので、未測定の食品が混ざると
    「その分は 0」として合計されてしまう。欠測を捏造しないため明示的に潰す。
    """
    out = {}
    for col in columns:
        values = df[col]
        out[col] = float('nan') if values.isna().any() else values.sum()
    return pd.Series(out)


# Sheets の日付シリアルの原点（1899-12-30）。Excel 互換で、1900年うるう年の
# 誤りを引き継いでいるため 1899-12-31 ではない
SHEET_EPOCH = pd.Timestamp('1899-12-30')


def read_sheet(spreadsheet, title):
    """シートを生値（UNFORMATTED_VALUE）で読む

    表示文字列で読むと、セルが日付型のとき年が落ちる。「9/6」と入力すると
    シートは日付シリアル 46271 として保存し表示だけ「9/6」にするので、
    表示を読むと 0001-09-06 として解釈されてしまう（実際に起きた）。
    """
    ws = spreadsheet.worksheet(title)
    return pd.DataFrame(ws.get_all_records(value_render_option='UNFORMATTED_VALUE'))


def parse_dates(values):
    """日付列を Timestamp に直す。シリアル値と文字列が混在してよい

    シートに日付として入れれば数値（シリアル）、`2026-09-06` を文字列として
    入れれば文字列で届く。どちらも同じ日付になるようにする。
    """
    s = pd.Series(values)
    serial = pd.to_numeric(s, errors='coerce')
    out = pd.to_datetime(s.where(serial.isna()), errors='coerce')
    from_serial = SHEET_EPOCH + pd.to_timedelta(serial, unit='D')
    return out.fillna(from_serial).dt.normalize()


def build_recipes(df_recipe, df_master):
    """
    レシピシートから「可食部100g当たり」のレシピ栄養値を作る。

    材料の合計を、調理後の実測総重量で割る。圧力鍋では水分が飛んで
    総重量が変わるので、材料の合計グラムでは割らない。
    """
    if df_recipe.empty or 'recipe_name' not in df_recipe.columns:
        return pd.DataFrame(columns=['name', 'source'] + NUTRIENTS), []

    df = df_recipe.copy()
    # 最初の材料行にだけ書けばよい列を下方向に埋める
    df['recipe_name'] = df['recipe_name'].replace('', pd.NA).ffill()
    df['cooked_total_g'] = pd.to_numeric(
        df['cooked_total_g'].replace('', pd.NA), errors='coerce').ffill()
    df['grams'] = pd.to_numeric(df['grams'], errors='coerce')
    df = df.dropna(subset=['recipe_name', 'name', 'grams'])

    merged = df.merge(df_master[['name'] + NUTRIENTS], on='name', how='left')
    unknown = merged[merged['energy_kcal'].isna() & merged['name'].notna()]['name'].unique()

    rows = []
    for recipe_name, group in merged.groupby('recipe_name', sort=False):
        cooked = group['cooked_total_g'].iloc[0]
        if not cooked or pd.isna(cooked) or cooked <= 0:
            raise ValueError(
                f"レシピ「{recipe_name}」の cooked_total_g が未入力です。"
                f"調理後の総重量を実測して入れてください"
            )
        scaled = group[NUTRIENTS].mul(group['grams'] / 100.0, axis=0)
        total = _sum_strict(scaled, NUTRIENTS)
        rec = (total / cooked * 100.0).to_dict()
        rec['name'] = recipe_name
        rec['source'] = 'recipe'
        rows.append(rec)

    return pd.DataFrame(rows)[['name', 'source'] + NUTRIENTS], list(unknown)


def resolve_log(df_log, df_foods):
    """食事ログの1行ごとに栄養値を出す。名前が引けない行は捨てずに返して報告する"""
    if df_log.empty or 'name' not in df_log.columns:
        empty = pd.DataFrame(columns=LOG_COLUMNS + NUTRIENTS)
        empty['date'] = pd.to_datetime(empty['date'])
        return empty, {'unknown_names': [], 'bad_date': 0, 'bad_grams': 0}

    df = df_log.copy()
    df = df[df['name'].astype(str).str.strip() != '']
    df['grams'] = pd.to_numeric(df['grams'], errors='coerce')
    df['date'] = parse_dates(df['date'])

    bad_date = df[df['date'].isna()]
    bad_grams = df[df['date'].notna() & df['grams'].isna()]
    df = df.dropna(subset=['date', 'grams'])

    merged = df.merge(df_foods[['name'] + NUTRIENTS], on='name', how='left')
    unknown = merged[merged['energy_kcal'].isna()]['name'].unique()

    merged[NUTRIENTS] = merged[NUTRIENTS].mul(merged['grams'] / 100.0, axis=0)
    return merged, {
        'unknown_names': list(unknown),
        'bad_date': len(bad_date),
        'bad_grams': len(bad_grams),
    }


def aggregate_daily(df_entries):
    """日次に集計する。列名はレポート側が読む既存の名前に合わせる"""
    if df_entries.empty:
        columns = [REPORT_ALIASES.get(c, c) for c in NUTRIENTS]
        return pd.DataFrame(index=pd.DatetimeIndex([], name='date'), columns=columns)

    daily = (df_entries
             .groupby(df_entries['date'].dt.normalize())
             .apply(lambda g: _sum_strict(g, NUTRIENTS), include_groups=False))
    daily.index.name = 'date'

    daily = daily.rename(columns=REPORT_ALIASES)
    ordered = list(REPORT_ALIASES.values())
    ordered += [c for c in daily.columns if c not in ordered]
    return daily[ordered].round(3)


def all_names(df_master, recipe_names, seed_names):
    """food_master へ流し込む名前の全件（成分表 + 手動登録 + レシピ + seed）

    スマホの Sheets アプリで2,538件でも実用的に絞り込めることを実機で確認した
    ため、これが既定。レシピ名を必ず含めるのが要点で、これが無いと鍋を登録しても
    ドロップダウンから選べない。
    """
    names = set(df_master['name'].dropna().astype(str))
    names |= set(str(n) for n in recipe_names if str(n).strip())
    names |= set(str(n) for n in seed_names if str(n).strip())
    return sorted(names)


def select_candidates(df_master, recipe_names, entry_names, seed_names, top_n):
    """
    food_master タブへ流し込む候補名を選ぶ（純関数）。

    実機では2,538件でも絞り込めたので既定は all_names だが、候補を絞りたい
    ときのために残す（--candidates）。次の和集合に絞る:
      - foods_master.csv の手動登録行（source != 'mext'。冷凍食品など）
      - レシピ名
      - 使用実績（entries.csv の name の出現回数）上位 top_n 件
      - seed_names（config/food_def.yaml の手書き初期候補）

    Args:
        df_master: foods_master.csv 相当の DataFrame（'name', 'source' 列を持つ）
        recipe_names: レシピ名の列（list/Series/Index）
        entry_names: entries.csv の 'name' 列（pd.Series）。実績が無ければ空でよい
        seed_names: 手書きの初期候補（list）
        top_n: 使用実績から採る件数の上限

    Returns:
        候補名のソート済みリスト（重複なし）
    """
    manual = set(df_master.loc[df_master['source'] != 'mext', 'name']
                 .dropna().astype(str))
    recipes = set(str(n) for n in recipe_names if str(n).strip())
    seeds = set(str(n) for n in seed_names if str(n).strip())

    top = set()
    if entry_names is not None and len(entry_names):
        counts = pd.Series(entry_names).dropna().astype(str)
        counts = counts[counts.str.strip() != '']
        top = set(counts.value_counts().head(top_n).index)

    return sorted(manual | recipes | top | seeds)


def detect_empty_sheet_failure(df_entries, entries_csv):
    """シートが0件なのに既存 CSV に行があるか（＝取得側の沈黙故障の疑い）

    entries.csv の出所はシートだけなので、この不一致は故障を意味する。
    daily.csv には Cronometer 由来の過去記録が混ざっており同じ判定は使えない。
    """
    if not df_entries.empty:
        return False
    if not Path(entries_csv).exists():
        return False
    return len(pd.read_csv(entries_csv)) > 0


def _ensure_worksheet(spreadsheet, title, header, rows=1000):
    """タブが無ければヘッダ付きで作る。既にあれば何もしない（値に触れない）"""
    try:
        ws = spreadsheet.worksheet(title)
        return ws, False
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=rows,
                                       cols=max(len(header), 5))
        ws.update([header], 'A1')
        return ws, True


def setup_worksheets(spreadsheet):
    """
    入力用の3タブを冪等に作る。

    既存タブの値には一切触れない（記録済みのログ・レシピを消さないため）。
    ドロップダウンの参照範囲は候補の件数に依存するので、ここでは張らない
    （sync_master が担う）。
    """
    specs = [(MASTER_SHEET, ['name']), (RECIPE_SHEET, RECIPE_COLUMNS),
             (LOG_SHEET, LOG_COLUMNS)]
    created = []
    requests = []
    for title, header in specs:
        ws, is_new = _ensure_worksheet(spreadsheet, title, header)
        if is_new:
            created.append(title)
        requests.append({'repeatCell': {
            'range': {'sheetId': ws.id, 'startRowIndex': 0, 'endRowIndex': 1,
                      'startColumnIndex': 0, 'endColumnIndex': len(header)},
            'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}},
            'fields': 'userEnteredFormat.textFormat.bold'}})
        requests.append({'updateSheetProperties': {
            'properties': {'sheetId': ws.id,
                           'gridProperties': {'frozenRowCount': 1}},
            'fields': 'gridProperties.frozenRowCount'}})
    spreadsheet.batch_update({'requests': requests})
    return created


def sync_master(spreadsheet, names):
    """
    food_master タブへ候補を流し込み、food_recipe / food_log の name 列の
    ドロップダウン参照範囲を張り直す。

    ドロップダウンにするのは表記ゆれを構造的に潰すため。strict=False で
    未登録の食品（冷凍食品など）も一旦書けるようにする（強制すると
    登録するまで記録自体が止まる）。
    """
    ws_master = spreadsheet.worksheet(MASTER_SHEET)
    n = len(names)
    ws_master.resize(rows=max(n + 1, 2), cols=1)
    ws_master.update([['name']], 'A1')
    if n:
        ws_master.update([[nm] for nm in names], f'A2:A{n + 1}')

    ref_end = max(n + 1, 2)
    ref = f"={MASTER_SHEET}!$A$2:$A${ref_end}"

    ws_recipe = spreadsheet.worksheet(RECIPE_SHEET)
    ws_log = spreadsheet.worksheet(LOG_SHEET)
    requests = []
    for ws, columns in ((ws_recipe, RECIPE_COLUMNS), (ws_log, LOG_COLUMNS)):
        col = columns.index('name')
        requests.append({'setDataValidation': {
            'range': {
                'sheetId': ws.id,
                'startRowIndex': 1,
                'startColumnIndex': col,
                'endColumnIndex': col + 1,
            },
            'rule': {
                'condition': {'type': 'ONE_OF_RANGE',
                              'values': [{'userEnteredValue': ref}]},
                'showCustomUi': True,
                'strict': False,
            },
        }})
    spreadsheet.batch_update({'requests': requests})
