"""
setup-form / fetch の共通手順と、サブコマンドの引数

**questionId の扱いはここで変えない。** `updateItem` は questionId を明示しないと
再採番し、過去の回答が孤立する（docs/forms.md）。突き合わせ（question_id 明示 →
kind ごとの出現順）と削除の安全装置（--allow-kind-replace が無ければ削除せず
GoogleFormsError）は gforms_client.sync_questions が持つ。
"""

import sys
from pathlib import Path

import pandas as pd
import yaml

from lib.clients import gdrive_client, gforms_client
from lib.forms import defs
from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir

BASE_DIR = Path(__file__).resolve().parents[3]
PERSONAL_FILE = BASE_DIR / 'config' / 'personal.yaml'


def move_new_form_to_drive(form_id):
    """新規作成したフォームを config/personal.yaml の gdrive.folder_id 配下へ移す

    forms.create は親を指定できずマイドライブ直下に作る。移動に失敗しても
    フォーム自体は作成済みなので form_id は失わせず、warning を出して続行する。
    """
    if not PERSONAL_FILE.exists():
        print(f'警告: {PERSONAL_FILE} が無い。Drive フォルダへの移動をスキップ',
              file=sys.stderr)
        return
    with open(PERSONAL_FILE, encoding='utf-8') as f:
        personal = yaml.safe_load(f) or {}
    folder_id = (personal.get('gdrive') or {}).get('folder_id')
    if not folder_id:
        print('警告: config/personal.yaml に gdrive.folder_id が無い。'
              'Drive フォルダへの移動をスキップ', file=sys.stderr)
        return
    try:
        drive_service = gdrive_client.create_service()
        gdrive_client.move_to_folder(drive_service, form_id, folder_id)
        print(f'Drive フォルダへ移動した: {folder_id}', file=sys.stderr)
    except Exception as e:
        print(f'警告: Drive フォルダへの移動に失敗（フォームは作成済み）: {e}',
              file=sys.stderr)


def setup_form(load, def_file, build_items, *, update, allow_kind_replace=False,
               before_delete=None, backfill=None):
    """フォームを新規作成するか、既存フォームを yaml に合わせる

    load: 定義を読む引数なしの関数（form_id を書き戻した後に読み直すため値でなく関数）
    build_items: conf -> item spec リスト
    before_delete: (service, conf, leftover) -> None。--allow-kind-replace で
        既存の質問が削除される直前に呼ぶ（未取り込み回答の検査など。止めるなら sys.exit）
    backfill: (conf, form) -> {key: questionId}。sync 後のフォームから yaml へ
        書き戻す questionId（Issue #176）。None なら書き戻さない
    """
    conf = load()
    items = build_items(conf)

    service = gforms_client.create_service()

    if conf.get('form_id'):
        if not update:
            print(f"フォームは作成済み: {conf['form_id']}")
            print('選択肢や質問文を yaml に合わせ直すなら --update')
            return
        existing_form = gforms_client.get_form(service, conf['form_id'])
        # フラグの有無にかかわらず、削除される可能性がある質問を先に列挙する。
        # フラグ無しで leftover があっても自前で止めない。sync_questions の
        # 既定のガード（GoogleFormsError）が唯一の失敗経路になるほうが
        # 分岐が増えない
        leftover = gforms_client.preview_kind_mismatch(items, existing_form)
        if leftover:
            if allow_kind_replace and before_delete:
                before_delete(service, conf, leftover)
            print('フォームから外れる（削除対象になりうる）既存の質問:')
            for i in leftover:
                print(f"  - {i.get('title')} ({gforms_client._question_kind(i)})")
        gforms_client.sync_questions(service, conf['form_id'], items,
                                     existing_form=existing_form,
                                     allow_kind_replace=allow_kind_replace)
        # 画面タイトルは item ではないので sync_questions が触らない。
        # questionId には影響しないが、差分があるときだけ叩く
        current_title = existing_form.get('info', {}).get('title')
        if conf.get('form_title') and current_title != conf['form_title']:
            gforms_client.update_form_info(service, conf['form_id'],
                                           conf['form_title'])
            print(f"タイトルを更新: {current_title} -> {conf['form_title']}")
        print('フォームを yaml に合わせて更新した')
        form = gforms_client.get_form(service, conf['form_id'])
    else:
        form = gforms_client.create_form(service, conf['form_title'],
                                         document_title=conf['form_title'])
        print(f"フォーム作成: {form['formId']}")
        gforms_client.sync_questions(service, form['formId'], items)
        defs.save_form_id(def_file, form['formId'])
        # 新規作成時のみ Drive フォルダへの移動を試みる。--update では移動しない
        move_new_form_to_drive(form['formId'])
        form = gforms_client.get_form(service, form['formId'])

    if backfill:
        # yaml に questionId が埋まると、以後の sync_questions は並び順ではなく
        # id で突き合わせるようになる（Issue #176）
        ids_by_key = backfill(load(), form)  # save_form_id 後の yaml
        if ids_by_key:
            n = defs.save_question_ids(def_file, ids_by_key)
            print(f'question_id を yaml へ書き戻した: {n}件')

    print(f"質問: {list(gforms_client.question_id_by_title(form))}")
    print(f"回答用URL: {defs.responder_uri(form)}")
    print(f"編集用URL: https://docs.google.com/forms/d/{form['formId']}/edit")


def fetch_responses(form_id, *, non_interactive):
    """フォーム構成と全回答を取る。毎回全件を取り直す（差分取得はしない）"""
    service = gforms_client.create_service(interactive=not non_interactive)
    form = gforms_client.get_form(service, form_id)

    print(f"回答取得中: {form_id}", file=sys.stderr)
    responses = gforms_client.list_responses(service, form_id)
    print(f"取得: {len(responses)}件", file=sys.stderr)
    return form, responses


def warn_if_no_responses(responses, existing) -> None:
    """既存行があるのに0件は取得側の故障を疑う

    マージするため CSV は消えないが、以後ずっと止まったままになる。
    """
    if not responses and existing is not None and len(existing) > 0:
        print('警告: 既存CSVに行があるのに回答が0件。'
              'フォームの差し替えかAPIの異常を疑うこと', file=sys.stderr)


def read_existing(out_file: Path):
    return pd.read_csv(out_file) if Path(out_file).exists() else None


def save_merged(df, out_file, key, *, preserve_existing_on_nan=False, out=None):
    """key 列で既存 CSV とマージして書く

    out: 保存結果の表示先。show --update から呼ぶときは stdout を markdown
    専用に保つため stderr を渡す
    """
    out = out or sys.stdout
    ensure_dir(Path(out_file).parent)
    df = csv_utils.merge_csv_by_columns(
        df, out_file,
        key_columns=[key],
        parse_dates=[key],
        sort_by=[key],
        preserve_existing_on_nan=preserve_existing_on_nan,
    )
    df.to_csv(out_file, index=False)
    print(f"保存完了: {out_file} ({len(df)}件)", file=out)
    print(df.tail(), file=out)
    return df


def add_setup_arguments(parser):
    """setup-form サブコマンドの引数（各スクリプトと forms.py で揃える）"""
    parser.add_argument('--update', action='store_true',
                        help='既存フォームの質問文・選択肢を yaml に合わせる')
    parser.add_argument('--allow-kind-replace', action='store_true',
                        help='フォームから外れる既存の質問を実際に削除する'
                             '（--update と併用。退役・質問の種類の変更）。'
                             '既定では削除せずエラーで止まる')


def add_fetch_arguments(parser):
    parser.add_argument('--non-interactive', action='store_true',
                        help='トークンが無効ならブラウザを開かず落とす（cron 用）')


def add_show_arguments(parser):
    parser.add_argument('--days', type=int, default=7, help='直近N日（既定 7）')
    parser.add_argument('--update', action='store_true',
                        help='表示前に fetch で最新データを取得する')
