#!/usr/bin/env python
# coding: utf-8
"""
統一レポート生成スクリプト

body/sleep/mindの3つのレポートを統一的に生成する。

Usage:
    python generate_report.py body --days 7
    python generate_report.py sleep --week current
    python generate_report.py mind --month 11
    python generate_report.py all --days 7
    python generate_report.py body --interval daily --days 7
    python generate_report.py body --interval interval --weeks 8
    python generate_report.py body --days 7 --fetch  # データ取得してからレポート生成
"""

import sys
import subprocess
from pathlib import Path
import argparse


# スクリプトディレクトリ
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent

# レポートタイプとスクリプトのマッピング（interval -> report_type -> script_name）
REPORT_SCRIPTS = {
    'daily': {
        'body': 'generate_body_report_daily.py',
        'sleep': 'generate_sleep_report_daily.py',
        'mind': 'generate_mind_report_daily.py',
    },
    'interval': {
        'body': 'generate_body_report_interval.py',
        # sleep/mind は未実装
    },
}


def fetch_latest_data() -> bool:
    """
    最新データを取得（2日分）

    Returns
    -------
    bool
        成功時True、失敗時False
    """
    print("=== Fitbitデータ取得 ===")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / 'fetch_fitbit.py'), '--all'],
        cwd=str(PROJECT_ROOT)
    )
    if result.returncode != 0:
        print("Fitbit取得エラー")
        return False

    print("\n=== HealthPlanet体組成計データ取得 ===")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / 'fetch_healthplanet.py')],
        cwd=str(PROJECT_ROOT)
    )
    if result.returncode != 0:
        print("HealthPlanet取得エラー")
        return False

    print("\n=== 完了 ===\n")
    return True


def run_report_script(report_type: str, interval: str, args: argparse.Namespace) -> int:
    """
    レポート生成スクリプトを実行

    Parameters
    ----------
    report_type : str
        レポートタイプ（'body', 'sleep', 'mind'）
    interval : str
        集計間隔（'daily', 'interval'など）
    args : Namespace
        コマンドライン引数

    Returns
    -------
    int
        終了コード
    """
    # スクリプト名を取得
    interval_scripts = REPORT_SCRIPTS.get(interval)
    if not interval_scripts:
        print(f"エラー: 不明な集計間隔 '{interval}'")
        return 1

    script_name = interval_scripts.get(report_type)
    if not script_name:
        print(f"エラー: 不明なレポートタイプ '{report_type}'")
        return 1

    script_path = SCRIPT_DIR / script_name

    # 引数を構築
    cmd = [sys.executable, str(script_path)]

    if args.output:
        cmd.extend(['--output', str(args.output)])
    if args.days is not None:
        cmd.extend(['--days', str(args.days)])
    if args.weeks is not None:
        cmd.extend(['--weeks', str(args.weeks)])
    if args.week:
        cmd.extend(['--week', args.week])
    if args.month:
        cmd.extend(['--month', args.month])
    if args.year is not None:
        cmd.extend(['--year', str(args.year)])

    # スクリプト実行
    print(f"\n{'='*60}")
    print(f"実行: {report_type} レポート ({interval})")
    print(f"{'='*60}\n")

    result = subprocess.run(cmd)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description='統一レポート生成スクリプト',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s body --days 7                      # 体組成レポート（直近7日）
  %(prog)s sleep --week current               # 睡眠レポート（今週）
  %(prog)s mind --month 11                    # メンタルレポート（11月）
  %(prog)s all --days 7                       # 全レポート（直近7日）
  %(prog)s body --interval daily --days 7     # 明示的にdaily指定
  %(prog)s body --interval interval --weeks 8 # 週次レポート（8週間分）
  %(prog)s body --days 7 --fetch              # データ取得してからレポート生成（2日分）
  %(prog)s all --week current --fetch         # データ取得してから全レポート生成
        """
    )

    # レポートタイプ（位置引数）
    parser.add_argument(
        'type',
        choices=['body', 'sleep', 'mind', 'all'],
        help='レポートタイプ'
    )

    # 集計間隔
    parser.add_argument(
        '--interval',
        type=str,
        choices=['daily', 'interval'],
        default='daily',
        help='集計間隔（デフォルト: daily）'
    )

    # 共通パラメータ
    parser.add_argument('--output', type=Path, help='出力ディレクトリ')
    parser.add_argument('--days', type=int, help='分析対象の日数')
    parser.add_argument('--weeks', type=int, help='分析対象の週数（interval用）')
    parser.add_argument('--week', type=str, help='ISO週番号（例: 48）または "current"')
    parser.add_argument('--month', type=str, help='月番号（例: 11）または "current"')
    parser.add_argument('--year', type=int, help='年（--week/--month指定時に使用）')
    parser.add_argument('--fetch', action='store_true', help='レポート生成前に最新データを取得（2日分）')

    args = parser.parse_args()

    # データ取得
    if args.fetch:
        if not fetch_latest_data():
            print("データ取得に失敗しました")
            return 1

    # レポートタイプに応じて実行
    if args.type == 'all':
        # 全レポートを順次実行
        report_types = ['body', 'sleep', 'mind']
        exit_codes = []

        for report_type in report_types:
            exit_code = run_report_script(report_type, args.interval, args)
            exit_codes.append(exit_code)

        # いずれかが失敗していたら非ゼロを返す
        return max(exit_codes)
    else:
        # 単一レポート実行
        return run_report_script(args.type, args.interval, args)


if __name__ == '__main__':
    sys.exit(main())
