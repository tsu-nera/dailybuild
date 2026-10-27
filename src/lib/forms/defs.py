"""
フォーム定義（config/<form>_def.yaml）の読み書き

書き戻しは yaml をテキストで読み、対象の値だけ置換する。yaml.safe_dump で
丸ごと書き直すとコメント（設問を変えてはいけない理由など）が全部消えるため使わない。
"""

import re
from pathlib import Path

import yaml


def load_def(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def save_form_id(path: Path, form_id: str) -> None:
    """form_id の行だけ置換する"""
    path = Path(path)
    text = path.read_text()
    new_text, n = re.subn(r'^form_id:.*$', f'form_id: {form_id}', text,
                          count=1, flags=re.MULTILINE)
    if n != 1:
        raise ValueError(f'form_id の行が見つからない: {path}')
    path.write_text(new_text)


def save_question_ids(path: Path, ids_by_key: dict) -> int:
    """question_id だけ行編集で書き戻す（Issue #176）。書いた件数を返す

    questions: 配下の各エントリ（"  - key: <key>" で始まる行）を走査し、
    ids_by_key（{key: question_id}）にある key のエントリへ question_id を
    挿入・置換する。エントリの終端は「4スペース以上インデントされた
    プロパティ行が続く間」で判定する（次のエントリ・次の設問群の前置き
    コメント・ファイル末尾の空行より前に挿入するため）。既に
    question_id: 行があれば値だけ置換し、無ければエントリの最後の
    プロパティ行の直後に挿入する。
    """
    path = Path(path)
    lines = path.read_text().splitlines(keepends=True)

    entry_pattern = re.compile(r'^  - key: (\S+)\s*$')
    entry_starts = [i for i, line in enumerate(lines) if entry_pattern.match(line)]

    written = 0
    # 後ろのエントリから書き換える（挿入で行数が増えても、まだ処理していない
    # 前方のエントリの行インデックスに影響しない）
    for i in reversed(entry_starts):
        key = entry_pattern.match(lines[i]).group(1)
        if key not in ids_by_key:
            continue

        content_end = i + 1
        while content_end < len(lines) and re.match(r'^ {4}\S', lines[content_end]):
            content_end += 1

        qid_line_idx = None
        for j in range(i + 1, content_end):
            if re.match(r'^    question_id:', lines[j]):
                qid_line_idx = j
                break

        new_line = f'    question_id: {ids_by_key[key]}\n'
        if qid_line_idx is not None:
            lines[qid_line_idx] = new_line
        else:
            lines.insert(content_end, new_line)
        written += 1

    if written == 0:
        raise ValueError(f'question_id を書き込む対象の key が見つからない: '
                         f'{list(ids_by_key)} / {path}')

    path.write_text(''.join(lines))
    return written


def responder_uri(form: dict) -> str:
    return form.get('responderUri', f"https://docs.google.com/forms/d/{form['formId']}/viewform")
