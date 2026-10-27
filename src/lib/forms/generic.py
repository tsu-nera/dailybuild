"""
固有処理を持たないフォームの setup-form / fetch / show（scripts/forms.py が呼ぶ）

ファイルの置き場は規約で決まる。レジストリ（config/forms.yaml）の key から:
  定義: config/<key>_def.yaml（スキーマは lib.forms.schema）
  回答: レジストリの csv
  グリッド行構成の版履歴: data/<key>_grid_history.csv
"""

import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

from lib.forms import cli, defs, render, schema
from lib.forms.responses import grid_row_titles, record_history
from lib.utils.private_data import require_private_write

BASE_DIR = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Paths:
    def_file: Path
    csv_file: Path
    grid_history_file: Path


def paths_for(key: str, csv: str) -> Paths:
    """レジストリのエントリからファイルの置き場を決める"""
    return Paths(
        def_file=BASE_DIR / 'config' / f'{key}_def.yaml',
        csv_file=require_private_write(BASE_DIR / csv),
        grid_history_file=require_private_write(BASE_DIR / 'data' / f'{key}_grid_history.csv'),
    )


def setup_form(load, def_file, args, build_items=schema.build_items):
    cli.setup_form(load, def_file, build_items, update=args.update,
                   allow_kind_replace=args.allow_kind_replace,
                   backfill=schema.backfill_question_ids)


def fetch(conf, paths: Paths, *, non_interactive, out=None):
    if not conf.get('form_id'):
        # setup-form 前のフォームが日次 fetch に載っても、失敗し続けて
        # ステップが赤く出るのを避けるため正常終了する
        print(f'form_id が未設定のためスキップ（{paths.def_file}。'
              'setup-form で作成すること）', file=sys.stderr)
        return

    form, responses = cli.fetch_responses(conf['form_id'], non_interactive=non_interactive)

    existing = cli.read_existing(paths.csv_file)
    df = schema.build_dataframe(form, responses, conf)
    df = schema.carry_retired_values(df, existing, conf)
    cli.warn_if_no_responses(responses, existing)

    if schema.grid_rows(conf):
        record_history(form, grid_row_titles(form), paths.grid_history_file, 'グリッド行構成')

    # preserve_existing_on_nan は既定の False のまま使う（行単位の置換）。
    # True（セル単位マージ）にすると、自由記述を空で送り直した回答が来たときに
    # 旧行の値が生き残る。毎回全回答を取り直すので、主キーごとに行を置換すればよい
    # （退役した列だけは carry_retired_values が既存 CSV から引き継ぐ）
    cli.save_merged(df, paths.csv_file, schema.key_column(conf), out=out)


def show(conf, csv_file, name, days):
    df_all = schema.load_entries(csv_file, conf)

    today = dt.date.today()
    start = today - dt.timedelta(days=days - 1)
    df = df_all[df_all['date'].dt.date >= start].reset_index(drop=True)

    print(f'# {name}（{start:%Y-%m-%d} 〜 {today:%Y-%m-%d}）\n')
    if schema.unit(conf) == 'day':
        print(f"記録 {len(df)}日分（{days}日中）\n")
    else:
        # 被覆は統計の但し書きとして出すだけで、上げるべき目標としては出さない
        print(f"記録 {len(df)}件 / {df['date'].nunique()}日に記録あり（{days}日中）\n")

    print('## スコア\n')
    print(render.render_scores(df, conf))
    if schema.text_labels(conf):
        print('\n## コメント\n')
        print(render.render_comments(df, conf))
    if schema.unit(conf) == 'day':
        print('\n## 入力率\n')
        print(render.render_fill_rates(df, conf, days))


def load(paths: Paths) -> dict:
    return defs.load_def(paths.def_file)
