"""
データローディングユーティリティ

ベースライン計算を考慮した効率的なCSV読み込み
"""
from pathlib import Path
from typing import Optional
import pandas as pd


def load_csv_with_baseline_window(
    csv_path: Path,
    target_start_date: pd.Timestamp,
    target_end_date: pd.Timestamp,
    baseline_window: int = 60,
    date_column: str = 'date',
    index_col: Optional[str] = 'date'
) -> pd.DataFrame:
    """
    ベースライン計算を考慮してCSVを効率的に読み込む

    ベースライン計算のために、表示期間よりbaseline_window日前から
    データを読み込みます。これにより数年分のデータがあっても
    必要な期間だけをメモリに載せることができます。

    Parameters
    ----------
    csv_path : Path
        CSVファイルパス
    target_start_date : pd.Timestamp
        表示開始日
    target_end_date : pd.Timestamp
        表示終了日
    baseline_window : int
        ベースライン計算期間（日数）、デフォルト60日
    date_column : str
        日付列名、デフォルト'date'
    index_col : str, optional
        インデックス列名、デフォルト'date'
        Noneの場合はインデックスを設定しない

    Returns
    -------
    DataFrame
        必要な期間のデータ（ベースライン計算期間含む）
        データがない場合は空のDataFrameを返す

    Examples
    --------
    >>> # 2025年12月のレポートを生成する場合（HRVは60日のベースラインが必要）
    >>> df = load_csv_with_baseline_window(
    ...     csv_path=Path('data/fitbit/hrv.csv'),
    ...     target_start_date=pd.Timestamp('2025-12-01'),
    ...     target_end_date=pd.Timestamp('2025-12-31'),
    ...     baseline_window=60
    ... )
    >>> # 実際には2025-10-02から2025-12-31までのデータが読み込まれる
    """
    if not csv_path.exists():
        return pd.DataFrame()

    # ベースライン計算のために拡張した期間
    load_start = target_start_date - pd.Timedelta(days=baseline_window)

    # CSV読み込み
    if index_col:
        df = pd.read_csv(csv_path, parse_dates=[date_column], index_col=index_col)
        # 必要な期間だけフィルタ（インデックスを使用）
        mask = (df.index >= load_start) & (df.index <= target_end_date)
    else:
        df = pd.read_csv(csv_path)
        # 日付列を明示的にTimestampに変換（タイムゾーンをローカライズ）
        df[date_column] = pd.to_datetime(df[date_column], format='ISO8601', utc=True)
        # タイムゾーンナイーブに変換（比較のため）
        df[date_column] = df[date_column].dt.tz_localize(None)
        # 必要な期間だけフィルタ（列を使用）
        mask = (df[date_column] >= load_start) & (df[date_column] <= target_end_date)

    return df[mask]


def determine_target_period(
    week: Optional[int],
    month: Optional[int],
    year: Optional[int],
    days: Optional[int]
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    引数から表示対象期間を決定

    Parameters
    ----------
    week : int, optional
        週番号
    month : int, optional
        月番号
    year : int, optional
        年
    days : int, optional
        直近N日分

    Returns
    -------
    tuple[pd.Timestamp, pd.Timestamp]
        (start_date, end_date) のタプル
    """
    if week is not None:
        # 週次
        start_date = pd.Timestamp.fromisocalendar(year, week, 1)
        end_date = pd.Timestamp.fromisocalendar(year, week, 7)
    elif month is not None:
        # 月次
        start_date = pd.Timestamp(year=year, month=month, day=1)
        # 月末日を取得
        if month == 12:
            end_date = pd.Timestamp(year=year, month=12, day=31)
        else:
            end_date = pd.Timestamp(year=year, month=month+1, day=1) - pd.Timedelta(days=1)
    elif days is not None:
        # 直近N日
        end_date = pd.Timestamp.now().normalize()
        start_date = end_date - pd.Timedelta(days=days-1)
    else:
        # デフォルト（エラーケース、呼び出し側でハンドルすべき）
        raise ValueError("week, month, またはdaysのいずれかを指定してください")

    return start_date, end_date
