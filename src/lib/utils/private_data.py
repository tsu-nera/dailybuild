"""
非公開データ（dailybuild-private）への参照チェック

dailybuild は public リポジトリのため、お金・時間・気分・CBT などの非公開
データは別リポジトリ dailybuild-private が持ち、data/ 配下へ symlink で
参照している。

symlink が張られていない環境（新マシン、git worktree など）では参照先が
dailybuild 内の実在しないパスに解決され、取得スクリプトが「データ0件」として
正常終了してしまう。欠測を捏造しないよう、読み書きの前に必ず
require_private_path() で落とす。

親ディレクトリの存在では判定しない。data/emotion.csv のようにファイル単体を
symlink する場合、symlink が無くても親の data/ は dailybuild 側に実在して
しまい、チェックをすり抜けるため。解決先が private リポジトリ配下にあるか
どうかで判定する。
"""

from pathlib import Path

PRIVATE_REPO = 'dailybuild-private'


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
