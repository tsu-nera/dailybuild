"""
行動イベントの正規化ストリーム（reports/events.jsonl）

ソースごとにばらばらな時刻表現（naive / aware / ISO 文字列）を 1行1イベントの
JSON Lines に揃える。ソース別アダプタ（sources）と、結合・件数検査・書き出し
（build）に分ける。scripts/events.py の build サブコマンドから利用する。
"""
