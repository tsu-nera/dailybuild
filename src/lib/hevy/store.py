"""
Hevy workouts.csv の書き込みガード

Hevy の export は常に全履歴を含むため、行数は基本的に単調増加する
（Hevy 側でワークアウトを削除した場合を除く）。新しい export の行数が
既存 CSV より少ないとき、それは Hevy 側の削除ではなく取得の故障
（別ファイルを掴んだ・空の export を落とした等）を疑うべきで、黙って
上書きすると過去のセット記録が消える。

このガードは `save_workouts()` に閉じる。`require_private_path()` は
モジュール定数の初期化時にのみ呼び、関数内では呼ばない
（`lib.exercise_source.EXERCISE_CSV_FILE` と同じ形。テストが tmp_path を
渡せるようにするため）。
"""

from pathlib import Path

from lib.utils.private_data import ensure_dir, require_private_path

REPO_ROOT = Path(__file__).resolve().parents[3]
CSV_FILE = require_private_path(REPO_ROOT / 'data' / 'hevy' / 'workouts.csv')


class WorkoutsShrankError(RuntimeError):
    """新しい export の行数が既存 CSV より少ない場合に投げる"""


def _count_data_rows(path: Path) -> int:
    """CSV のデータ行数（ヘッダを除く）を数える"""
    with open(path, 'rb') as f:
        line_count = sum(1 for _ in f)
    return max(line_count - 1, 0)


def save_workouts(csv_bytes: bytes, out_path: Path = CSV_FILE,
                   force: bool = False) -> tuple[int, int]:
    """新しい export を書き込む

    Parameters
    ----------
    csv_bytes : bytes
        新しい export の内容
    out_path : Path
        書き込み先（既定は data/hevy/workouts.csv）
    force : bool
        True なら行数が減っていても書き込む

    Returns
    -------
    tuple[int, int]
        (既存行数, 新行数)。既存 CSV が無い場合は既存行数を 0 とする

    Raises
    ------
    WorkoutsShrankError
        新行数が既存行数より少なく、force が False の場合
    """
    existing_rows = _count_data_rows(out_path) if out_path.exists() else 0

    tmp_path = out_path.with_suffix(out_path.suffix + '.tmp')
    ensure_dir(out_path.parent)
    tmp_path.write_bytes(csv_bytes)
    new_rows = _count_data_rows(tmp_path)

    if existing_rows > 0 and new_rows < existing_rows and not force:
        tmp_path.unlink()
        raise WorkoutsShrankError(
            f"新しい export の行数が既存より少ない: "
            f"既存 {existing_rows}行 -> 新規 {new_rows}行。"
            "Hevy 側の削除でなければ取得の故障。"
            "上書きするなら --force を付けること"
        )

    tmp_path.replace(out_path)
    return existing_rows, new_rows
