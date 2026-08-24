"""
非公開データ（dailybuild-private）への参照チェック

dailybuild は public リポジトリのため、お金・時間・気分・CBT などの非公開
データは別リポジトリ dailybuild-private が持ち、data/ 配下へ symlink で
参照している。

symlink が張られていない環境（新マシン、git worktree など）では参照先が
dailybuild 内の実在しないパスに解決される。読み取りは「データ0件」として
正常終了し、書き込みは mkdir(parents=True) が public 側に実体ディレクトリを
作ってしまう（以後 merge 対象の履歴を見失い、欠測を捏造する）。

いずれも解決先が private リポジトリ配下にあるかどうかで判定する。
親ディレクトリの存在では判定しない。symlink が無くても public 側の
ディレクトリが実在してチェックをすり抜けるため。

- require_private_path(): 非公開パスを明示的に検証する（呼び出し側が指定）
- require_private_write(): 書き込み直前の関門。repo 内の data/ reports/ 配下
  なのに private へ解決されないパスだけを落とす。tmp などリポジトリ外の
  パスは対象外なのでテストの一時ファイルは素通りする
"""

from pathlib import Path

PRIVATE_REPO = 'dailybuild-private'
REPO_ROOT = Path(__file__).resolve().parents[3]
PRIVATE_DIRS = ('data', 'reports')


def require_private_path(path: Path) -> Path:
    """
    非公開データのパスが dailybuild-private に解決されることを確認する。

    Args:
        path: 非公開データのパス（ファイルまたはディレクトリ。未作成でもよい）

    Returns:
        検証済みの path（呼び出し側はそのまま読み書きに使える）

    Raises:
        FileNotFoundError: symlink 未設定、または解決先が private リポジトリ外
    """
    if PRIVATE_REPO in Path(path).resolve().parts:
        return path

    raise FileNotFoundError(
        f"非公開データが {PRIVATE_REPO} に解決されません: {path}\n"
        f"symlink が未設定の可能性があります。\n"
        f"セットアップ手順は CLAUDE.md の「非公開データ」を参照してください。"
    )


def require_private_write(path: Path) -> Path:
    """
    書き込み先が public リポジトリの data/ reports/ に落ちていないか確認する。

    symlink が張られていれば path は dailybuild-private へ解決されるので素通り
    する。リポジトリ外（tmp など）も対象外。

    Args:
        path: 書き込み先のパス（未作成でもよい）

    Returns:
        検証済みの path

    Raises:
        FileNotFoundError: symlink 未設定で public 側へ書こうとしている
    """
    resolved = Path(path).resolve()
    if REPO_ROOT not in resolved.parents:
        return path

    top = resolved.relative_to(REPO_ROOT).parts[0]
    if top not in PRIVATE_DIRS:
        return path

    raise FileNotFoundError(
        f"{top}/ が {PRIVATE_REPO} に解決されないまま書き込もうとしました: {path}\n"
        f"symlink が未設定です。scripts/setup_private_links.sh を実行してください。"
    )


def ensure_dir(path: Path) -> Path:
    """
    書き込み先ディレクトリを作る。public 側へ落ちている場合は作らずに落とす。

    mkdir(parents=True) を素で呼ぶと symlink 未設定の環境で public リポジトリ
    内に実体ディレクトリを作ってしまうため、data/ reports/ 配下への mkdir は
    すべてこれを経由する。
    """
    require_private_write(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
