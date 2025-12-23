"""
レポート生成スクリプト共通の引数処理ユーティリティ
"""
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional
import pandas as pd


def add_common_report_args(parser, default_output: Path, default_days: Optional[int] = None):
    """
    レポート生成スクリプトの共通引数を追加

    Parameters
    ----------
    parser : ArgumentParser
        argparseパーサー
    default_output : Path
        デフォルト出力ディレクトリ
    default_days : int, optional
        --daysのデフォルト値（Noneの場合は全データ）
    """
    parser.add_argument(
        '--output',
        type=Path,
        default=default_output,
        help='出力ディレクトリ'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=default_days,
        help='分析対象の日数（デフォルト: 全データ）'
    )
    parser.add_argument(
        '--week',
        type=str,
        default=None,
        help='ISO週番号（例: 48）または "current" で今週を指定'
    )
    parser.add_argument(
        '--month',
        type=str,
        default=None,
        help='月番号（例: 11）または "current" で今月を指定'
    )
    parser.add_argument(
        '--year',
        type=int,
        default=None,
        help='年（--week/--month指定時に使用、デフォルト: 今年）'
    )


def parse_period_args(args) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """
    週次・月次の引数を解析

    Parameters
    ----------
    args : argparse.Namespace
        パース済み引数

    Returns
    -------
    tuple
        (week, month, year) のタプル
        weekとmonthは排他的（両方Noneの場合もあり）
    """
    week = None
    month = None
    year = args.year

    if args.week is not None:
        if args.week.lower() == 'current':
            iso_cal = datetime.now().isocalendar()
            week = iso_cal[1]
            if year is None:
                year = iso_cal[0]
        else:
            week = int(args.week)
            if year is None:
                year = datetime.now().year

    elif args.month is not None:
        if args.month.lower() == 'current':
            now = datetime.now()
            month = now.month
            year = year or now.year
        else:
            month = int(args.month)
            year = year or datetime.now().year

    return week, month, year


def determine_output_dir(
    base_dir: Path,
    report_type: str,
    default_output: Path,
    week: Optional[int],
    month: Optional[int],
    year: Optional[int]
) -> Path:
    """
    出力ディレクトリを決定

    Parameters
    ----------
    base_dir : Path
        プロジェクトのベースディレクトリ
    report_type : str
        レポートタイプ（'body', 'sleep', 'mind'など）
    default_output : Path
        デフォルト出力ディレクトリ
    week : int, optional
        週番号
    month : int, optional
        月番号
    year : int, optional
        年

    Returns
    -------
    Path
        出力ディレクトリパス
    """
    if week is not None:
        return base_dir / f'reports/{report_type}/weekly/{year}-W{week:02d}'
    elif month is not None:
        return base_dir / f'reports/{report_type}/monthly/{year}-{month:02d}'
    else:
        return default_output


def filter_dataframe_by_period(
    df: pd.DataFrame,
    date_column: str,
    week: Optional[int],
    month: Optional[int],
    year: Optional[int],
    days: Optional[int],
    is_index: bool = False
) -> pd.DataFrame:
    """
    DataFrameを期間でフィルタリング

    Parameters
    ----------
    df : DataFrame
        フィルタリング対象のDataFrame
    date_column : str
        日付列の名前（is_index=Trueの場合はindex名）
    week : int, optional
        週番号
    month : int, optional
        月番号
    year : int, optional
        年
    days : int, optional
        直近N日分
    is_index : bool
        日付列がindexかどうか

    Returns
    -------
    DataFrame
        フィルタリング済みDataFrame
    """
    if week is not None:
        if year is None:
            year = datetime.now().year

        if is_index:
            df_temp = df.reset_index()
        else:
            df_temp = df.copy()

        # 既にdatetime型でない場合のみ変換
        if not pd.api.types.is_datetime64_any_dtype(df_temp[date_column]):
            df_temp[date_column] = pd.to_datetime(df_temp[date_column], format='ISO8601')
        df_temp['iso_week'] = df_temp[date_column].dt.isocalendar().week
        df_temp['iso_year'] = df_temp[date_column].dt.isocalendar().year
        df_temp = df_temp[(df_temp['iso_week'] == week) & (df_temp['iso_year'] == year)]
        df_temp = df_temp.drop(columns=['iso_week', 'iso_year'])

        if is_index:
            df_temp = df_temp.set_index(date_column)

        return df_temp

    elif month is not None:
        if year is None:
            year = datetime.now().year

        if is_index:
            df_temp = df.reset_index()
        else:
            df_temp = df.copy()

        # 既にdatetime型でない場合のみ変換
        if not pd.api.types.is_datetime64_any_dtype(df_temp[date_column]):
            df_temp[date_column] = pd.to_datetime(df_temp[date_column], format='ISO8601')
        df_temp = df_temp[
            (df_temp[date_column].dt.month == month) &
            (df_temp[date_column].dt.year == year)
        ]

        if is_index:
            df_temp = df_temp.set_index(date_column)

        return df_temp

    elif days is not None:
        return df.tail(days)

    else:
        return df
