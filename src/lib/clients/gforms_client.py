#!/usr/bin/env python
# coding: utf-8
"""
Google Forms API クライアント

気分記録のフォームを生成し、回答を直接読む。回答先スプレッドシートは
作らない（Forms API に回答先のリンク設定が無く、そこだけ手作業として
残ってしまうため）。

サービスアカウントは使えない。Drive の storageQuota が 0 でファイルを
所有できず、forms.create が 500 Internal になる。OAuth でユーザー自身が
所有する。

認証情報:
  config/googlehealth_creds.json  OAuth クライアント（Google Health と共用）
  config/gforms_token.json        認可済みトークン（authorize() が生成）
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).parent.parent.parent.parent
CREDS_FILE = BASE_DIR / 'config/googlehealth_creds.json'
TOKEN_FILE = BASE_DIR / 'config/gforms_token.json'

SCOPES = [
    'https://www.googleapis.com/auth/forms.body',
    'https://www.googleapis.com/auth/forms.responses.readonly',
]


class GoogleFormsError(RuntimeError):
    """Google Forms API 呼び出しの失敗"""


def authorize(interactive: bool = True) -> Credentials:
    """認証済み Credentials を返す（googlehealth_client.authorize と同じ流儀）"""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
        return creds

    if not interactive:
        raise GoogleFormsError(
            f'有効なトークンがない: {TOKEN_FILE}。'
            'authorize(interactive=True) を対話環境で実行すること'
        )

    if not CREDS_FILE.exists():
        raise GoogleFormsError(f'OAuth クライアントがない: {CREDS_FILE}')

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=8080, access_type='offline', prompt='consent')
    TOKEN_FILE.write_text(creds.to_json())
    return creds


def create_service(interactive: bool = True):
    return build('forms', 'v1', credentials=authorize(interactive),
                 cache_discovery=False)


def create_form(service, title: str, document_title: str = None) -> dict:
    """空のフォームを作る。create では info.title 以外を渡せない"""
    info = {'title': title}
    if document_title:
        info['documentTitle'] = document_title
    return service.forms().create(body={'info': info}).execute()


def scale_item(title: str, low: int, high: int, low_label: str,
              high_label: str, required: bool = True) -> dict:
    """均等目盛（scaleQuestion）の item spec"""
    return {
        'title': title,
        'questionItem': {
            'question': {
                'required': required,
                'scaleQuestion': {
                    'low': low,
                    'high': high,
                    'lowLabel': low_label,
                    'highLabel': high_label,
                },
            },
        },
    }


def checkbox_item(title: str, choices: list, required: bool = True) -> dict:
    """チェックボックス（choiceQuestion）の item spec"""
    return {
        'title': title,
        'questionItem': {
            'question': {
                'required': required,
                'choiceQuestion': {
                    'type': 'CHECKBOX',
                    'options': [{'value': c} for c in choices],
                },
            },
        },
    }


def radio_item(title: str, choices: list, required: bool = True) -> dict:
    """ラジオボタン（choiceQuestion, type RADIO）の item spec"""
    return {
        'title': title,
        'questionItem': {
            'question': {
                'required': required,
                'choiceQuestion': {
                    'type': 'RADIO',
                    'options': [{'value': c} for c in choices],
                },
            },
        },
    }


def text_item(title: str, required: bool = False,
             question_id: str | None = None) -> dict:
    """記述式（textQuestion）の item spec

    question_id を渡すと questionItem.question.questionId に明示する
    （Issue #176）。yaml 側に questionId の台帳（backfill 済みの値）が
    あるとき、sync_questions の突き合わせを出現順（FIFO）でなく id で
    直接標的にできるようにするためのフック。None なら questionId を
    持たない spec になり、_match_specs_to_existing() は従来どおり
    kind-FIFO で突き合わせる。
    """
    item = {
        'title': title,
        'questionItem': {
            'question': {
                'required': required,
                'textQuestion': {'paragraph': False},
            },
        },
    }
    if question_id is not None:
        item['questionItem']['question']['questionId'] = question_id
    return item


def grid_item(title: str, rows: list, low: int, high: int, low_label: str,
             high_label: str, required: bool | list = True) -> dict:
    """選択式グリッド（questionGroupItem + grid）の item spec

    列は low..high の連番（文字列化）。scaleQuestion と違い Grid に
    低/高ラベル専用のフィールドが無いため、item の description に埋め込む
    （画面上は列見出しの上に説明文として出る）。

    行（rows）は questionGroupItem.questions[] の **出現順**で管理される。
    sync_questions() は行の対応付けもタイトルでなく出現順（FIFO）で行うため、
    rows の並びを変えると既存回答の questionId が別の行に付け替わる
    （docs/forms.md 参照。PHQ-9 の9問と同じ制約が行単位で効く）。

    required は bool なら全行に同じ値を、rows と同じ長さのリストなら
    行ごとの値を当てる（全行必須にすると、一部の行だけ記録したいときも
    毎回すべて答える必要が生じ、記録コストが上がる）。
    """
    if isinstance(required, bool):
        required_per_row = [required] * len(rows)
    else:
        required_per_row = list(required)
        if len(required_per_row) != len(rows):
            raise ValueError(
                f'required の長さ({len(required_per_row)})が'
                f'rows の長さ({len(rows)})と一致しない')
    columns = [str(n) for n in range(low, high + 1)]
    return {
        'title': title,
        'description': f'{low_label} ← → {high_label}',
        'questionGroupItem': {
            'questions': [
                {'required': r, 'rowQuestion': {'title': t}}
                for t, r in zip(rows, required_per_row)
            ],
            'grid': {
                'columns': {
                    'type': 'RADIO',
                    'options': [{'value': c} for c in columns],
                },
            },
        },
    }


def _question_kind(item: dict) -> str | None:
    """item から質問の種類を取り出す

    scaleQuestion / choiceQuestion / textQuestion に加え、グリッド
    （questionGroupItem）も1つの種類として扱う。フォーム全体で
    questionGroupItem は高々1個の運用を前提にしているため、これで
    kind ベースの突き合わせに乗せられる（行単位の対応付けは
    sync_questions() 側で別途 FIFO で行う）。
    """
    if 'questionGroupItem' in item:
        return 'questionGroupItem'
    question = item.get('questionItem', {}).get('question', {})
    for kind in ('scaleQuestion', 'choiceQuestion', 'textQuestion'):
        if kind in question:
            return kind
    return None


def _spec_question_id(spec: dict) -> str | None:
    """spec が明示している questionId。無ければ None（grid は対象外）"""
    return spec.get('questionItem', {}).get('question', {}).get('questionId')


def _existing_question_id(item: dict) -> str | None:
    """既存 item 自身の questionId。無ければ None（grid の group 自体には無い）"""
    return item.get('questionItem', {}).get('question', {}).get('questionId')


def _strip_question_id(spec: dict) -> dict:
    """createItem に渡す前に spec から questionId を取り除く（浅いコピー）

    元の spec dict は破壊的に変更しない。questionId を明示したまま
    createItem に送ると stale な id を新規 item に押しつけることになり、
    API が拒否するか、拒否されなくても意図しない対応付けが残る事故になる。
    """
    if 'questionItem' not in spec:
        return spec
    question = spec['questionItem']['question']
    if 'questionId' not in question:
        return spec
    new_question = dict(question)
    del new_question['questionId']
    return {**spec, 'questionItem': {**spec['questionItem'], 'question': new_question}}


def _match_specs_to_existing(items: list, existing_form: dict) -> tuple:
    """spec と既存 item の対応付け。(matched, leftover) を返す

    matched は items と同じ長さのリストで、各要素は対応する既存 item
    （無ければ None）。leftover はどの spec にも対応しなかった既存 item。

    preview_kind_mismatch() と sync_questions() の両方がこの関数に乗る
    （突き合わせ規則を1箇所にする。以前は2箇所に同じロジックが複製されて
    いた）。

    突き合わせは2パス（Issue #176）:
      パス1（id 明示）: spec が questionItem.question.questionId を持つ
        ものについて、既存 item から同じ questionId を持つものを探し、
        並び順を見ずに確定する。見つからなければ確定しない（= None のまま。
        パス2の kind-FIFO にもフォールバックしない）。yaml の questionId が
        古い／誤っているときに FIFO で無関係な item を誤って標的にすると
        silent に破損するため、そのような spec は createItem 行きにして
        既定のガード（対応しない既存 item が leftover として残り
        GoogleFormsError で止まる）に委ねる。
      パス2（kind-FIFO、現行踏襲）: パス1で id を明示していない spec に
        ついて、パス1で確定済みの item を除いた残りを kind ごとの
        バケットに入れ、出現順（フォーム側の並び順）に消費する。
    """
    existing_items = [i for i in existing_form.get('items', [])
                      if 'questionItem' in i or 'questionGroupItem' in i]

    id_to_existing = {}
    for item in existing_items:
        qid = _existing_question_id(item)
        if qid is not None:
            id_to_existing[qid] = item

    matched = [None] * len(items)
    used_item_ids = set()
    fifo_indices = []

    # パス1: id 明示
    for idx, spec in enumerate(items):
        spec_id = _spec_question_id(spec)
        if spec_id is None:
            fifo_indices.append(idx)
            continue
        existing_item = id_to_existing.get(spec_id)
        if existing_item is not None and existing_item.get('itemId') not in used_item_ids:
            matched[idx] = existing_item
            used_item_ids.add(existing_item.get('itemId'))
        # 見つからない／既に使用済みなら matched は None のまま（create 行き）

    # パス2: kind-FIFO（パス1で確定済みの item を除いた残りだけを消費する）
    existing_by_kind = {}
    for item in existing_items:
        if item.get('itemId') in used_item_ids:
            continue
        kind = _question_kind(item)
        existing_by_kind.setdefault(kind, []).append(item)

    for idx in fifo_indices:
        kind = _question_kind(items[idx])
        bucket = existing_by_kind.get(kind, [])
        if bucket:
            existing_item = bucket.pop(0)
            matched[idx] = existing_item
            used_item_ids.add(existing_item.get('itemId'))

    leftover = [i for i in existing_items if i.get('itemId') not in used_item_ids]
    return matched, leftover


def preview_kind_mismatch(items: list, existing_form: dict) -> list:
    """sync_questions が leftover と判定する既存 item を事前に返す

    sync_questions を allow_kind_replace=True で呼ぶ前に、削除される質問を
    人間が確認できるようにする用途（CLI 側で使う）。マッチングのロジックは
    _match_specs_to_existing() に一本化してある。ここでは
    createItem/updateItem のリクエストは組み立てない。
    """
    _, leftover = _match_specs_to_existing(items, existing_form)
    return leftover


def sync_questions(service, form_id: str, items: list,
                   existing_form: dict = None,
                   allow_kind_replace: bool = False) -> dict:
    """フォームの質問を items（望ましい item spec のリスト）に合わせる

    existing_form が None なら全 item を新規作成する。
    existing_form があれば、既存 item と items を突き合わせて
    createItem / updateItem に振り分ける（マッチングは
    _match_specs_to_existing() に一本化してある）。

    突き合わせは spec が questionItem.question.questionId を明示している
    かどうかで優先度が変わる（Issue #176）。明示があればそれを最優先し、
    フォーム側の並び順に関係なくその id を持つ item を標的にする。明示が
    無い spec は従来どおり「質問の種類」ごとの出現順（kind-FIFO）で
    対応付く。id を明示した spec がフォーム側に見つからない場合は
    kind-FIFO にフォールバックせず createItem 行きにする（詳細は
    _match_specs_to_existing() の docstring）。

    index で突き合わせてはいけない。questionId は item に紐づいて保持される
    ため、既存 item の型を作り変える（= 別の質問として updateItem する）と、
    過去の回答の questionId が新しい質問のものとして残ってしまう。

    さらに実機で確認した Forms API の癖として、updateItem の
    questionItem.question に questionId を明示しないと、たとえ既存 item を
    正しく標的にしていても **API 側が新しい questionId を割り当てて
    しまう**（title だけの変更でも起きる）。これをやると過去回答の
    questionId が古いままになり、CSV 側から二度と引けなくなる。
    そのため update する item には既存の questionId を明示的に埋め込む。

    グリッド（questionGroupItem）も同じ原則が要る。item 自体は他の kind と
    同様「questionGroupItem」という1つの kind として突き合わせるが、
    その中の行（questions[]）は **出現順（FIFO）**で対応付け、行ごとの
    questionId を明示的に引き継ぐ。タイトルで対応付けないのは PHQ-9 の
    9問と同じ理由: 行順を変える変更を検知できなくなるため
    （行順の変更は意図的な質問構成の変更であり、questionId を新しい行へ
    付け替えるのが正しい）。行が増えた分（既存より後ろ）は questionId を
    付けず、API に新規採番させる。

    既存 item のうち、items のどの kind にも対応しないものが残った場合
    （= leftover）は、既定では GoogleFormsError を投げて止まる。これは
    「画面で手編集された想定外の質問」を検出するためのガードで、
    質問の型を意図的に作り変える移行（例: scaleQuestion 1問 →
    questionGroupItem 化）のときだけ無条件に外すと事故る。そのため
    `allow_kind_replace=True` を明示したときだけ leftover を
    deleteItem で削除する opt-in にしてある（#103/#105 の
    `preserve_existing_on_nan` と同じ「既定は安全、意図的な変更のみ
    opt-in」という考え方）。deleteItem で消した item の questionId は
    フォーム側から失われるが、回答の値自体は API のレスポンスに残る。
    失われるのは questionId とどの質問かの対応付けだけで、旧 questionId を
    控えておけば生レスポンスから読める。ただし CSV に materialize されて
    いない回答（fetch していない最新回答）があると、その対応付けが取れる
    のは削除前のこの瞬間だけなので、値を失う前に必ず fetch を済ませておく
    こと（詳細は docs/forms.md の気分記録の節）。
    """
    if existing_form is None:
        requests = [
            {'createItem': {'item': _strip_question_id(item), 'location': {'index': i}}}
            for i, item in enumerate(items)
        ]
        return service.forms().batchUpdate(
            formId=form_id, body={'requests': requests}).execute()

    matched, leftover = _match_specs_to_existing(items, existing_form)

    create_requests = []
    update_requests = []
    final_index = 0
    for spec, existing_item in zip(items, matched):
        if existing_item is not None:
            kind = _question_kind(existing_item)
            if kind == 'questionGroupItem':
                existing_questions = existing_item.get(
                    'questionGroupItem', {}).get('questions', [])
                spec_questions = spec['questionGroupItem']['questions']
                new_questions = []
                for i, row in enumerate(spec_questions):
                    if i < len(existing_questions):
                        row = {**row,
                              'questionId': existing_questions[i].get('questionId')}
                    new_questions.append(row)
                update_item = {
                    'title': spec['title'],
                    'description': spec.get('description', ''),
                    'questionGroupItem': {
                        **spec['questionGroupItem'],
                        'questions': new_questions,
                    },
                }
                update_requests.append({
                    'updateItem': {
                        'item': update_item,
                        'location': {'index': final_index},
                        'updateMask': 'title,description,questionGroupItem',
                    },
                })
            else:
                existing_question_id = existing_item.get(
                    'questionItem', {}).get('question', {}).get('questionId')
                update_item = {
                    'title': spec['title'],
                    'questionItem': {
                        'question': {
                            **spec['questionItem']['question'],
                            'questionId': existing_question_id,
                        },
                    },
                }
                update_requests.append({
                    'updateItem': {
                        'item': update_item,
                        'location': {'index': final_index},
                        'updateMask': 'title,questionItem.question',
                    },
                })
        else:
            create_requests.append({
                'createItem': {'item': _strip_question_id(spec), 'location': {'index': final_index}},
            })
        final_index += 1

    delete_requests = []
    if leftover:
        if not allow_kind_replace:
            raise GoogleFormsError(
                '望ましい質問構成に対応しない既存の質問が残っている'
                '（画面で手編集された可能性がある）: '
                f"{[(i.get('title'), _question_kind(i)) for i in leftover]}"
            )
        # DeleteItemRequest に itemId フィールドは無く、location.index で
        # 指定する（実機で 400: "Unknown name 'itemId' ... Cannot find
        # field" を確認済み）。index はフォーム全体の item 配列（質問以外の
        # item も含む）上の現在位置で数える必要があるため、
        # existing_items（質問だけに絞った配列）ではなく
        # existing_form['items'] の生の並びから引く。
        full_items = existing_form.get('items', [])
        item_id_to_index = {
            item.get('itemId'): i for i, item in enumerate(full_items)
        }
        delete_requests = [
            {'deleteItem': {'location': {'index': item_id_to_index[i.get('itemId')]}}}
            for i in sorted(leftover,
                            key=lambda i: item_id_to_index[i.get('itemId')],
                            reverse=True)
        ]

    # delete を create/update より先に適用する。create/update の
    # location.index は「delete 後に残る item だけで数えた最終的な
    # 望ましい順序」の 0-origin 連番（leftover が無い場合と同じ計算式）。
    # batchUpdate は requests を先頭から順に現在の状態へ適用するため、
    # delete を後回しにすると leftover item がまだ残っている間に
    # create/update の絶対 index を適用することになり、意図しない位置へ
    # 挿入・移動されてしまう。
    #
    # deleteItem も location.index 指定になったため、delete 同士の順序は
    # 無関係ではない。batchUpdate は requests を逐次・累積的に適用するので、
    # ある item を index N で消すと、それより後ろの item は 1 つずつ index が
    # 詰まる。複数 leftover を削除するときに元の index の昇順で並べると、
    # 1件目の削除後に後続の削除対象の index がずれて誤った item を消す。
    # 降順（index の大きいものから）に並べれば、後の削除が先の削除対象の
    # index に影響しないため安全。
    #
    # 検証（3問 scale/checkbox/text → grid/checkbox/text 移行、
    # #104 のケース）:
    #   既存: [scale(idx0), checkbox(idx1), text(idx2)]
    #   leftover は scale(idx0) のみ → delete: index=0
    #   適用後の残り: [checkbox(0), text(1)]
    #   create（grid）は final_index=0 → [grid(0), checkbox(1), text(2)]
    #   update（checkbox）は final_index=1、update（text）は final_index=2
    #   → 最終順序 [grid(0), checkbox(1), text(2)] は期待どおり
    requests = delete_requests + create_requests + update_requests
    return service.forms().batchUpdate(
        formId=form_id, body={'requests': requests}).execute()


def get_form(service, form_id: str) -> dict:
    return service.forms().get(formId=form_id).execute()


def question_id_by_title(form: dict) -> dict:
    """質問タイトル -> questionId。回答の突き合わせに使う

    グリッドは item 自体にタイトルは無い（グリッドの見出しは行ごとの
    rowQuestion.title）。行名をそのままキーにする（build_dataframe 側は
    グリッド化前と同じ「質問タイトル」で引けるようにするため）。
    """
    result = {}
    for item in form.get('items', []):
        question = item.get('questionItem', {}).get('question')
        if question and 'questionId' in question:
            result[item.get('title')] = question['questionId']

        group = item.get('questionGroupItem')
        if group:
            for row in group.get('questions', []):
                title = row.get('rowQuestion', {}).get('title')
                question_id = row.get('questionId')
                if title and question_id:
                    result[title] = question_id
    return result


def list_responses(service, form_id: str) -> list:
    """全回答を返す。ページングは尽きるまで辿る"""
    responses = []
    page_token = None
    while True:
        res = service.forms().responses().list(
            formId=form_id, pageToken=page_token).execute()
        responses.extend(res.get('responses', []))
        page_token = res.get('nextPageToken')
        if not page_token:
            return responses


def answer_values(response: dict, question_id: str) -> list:
    """1回答から指定質問の値リストを取り出す。未回答なら空リスト"""
    answer = response.get('answers', {}).get(question_id)
    if not answer:
        return []
    return [a['value'] for a in answer.get('textAnswers', {}).get('answers', [])]


def update_form_info(service, form_id: str, title: str) -> dict:
    """フォームの画面タイトルを差し替える

    sync_questions とは別の batchUpdate にする。updateFormInfo は item に
    触らないので questionId には影響しないが、質問の同期と混ぜると
    「タイトルだけ直したいのに item も動いた」という切り分けができなくなる。

    documentTitle（Drive 上のファイル名）はここで変えられない。create の
    ときしか設定できず、後から updateFormInfo に載せると
    「document_title is read-only in subsequent requests」で 400 になる。
    改名したフォームは Drive 上の名前だけ旧称のまま残る。
    """
    return service.forms().batchUpdate(formId=form_id, body={'requests': [
        {'updateFormInfo': {'info': {'title': title}, 'updateMask': 'title'}},
    ]}).execute()
