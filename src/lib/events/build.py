"""
ソース別イベントの結合・件数検査・JSON Lines 書き出し

期待するソースのいずれかが 0 件なら書き出さずに失敗させる。どれかの fetch が
黙って壊れても events.jsonl だけは正常に生成される、という沈黙故障を作らない
ため。失敗時は既存の events.jsonl を上書きしない（欠けたストリームで置き換えない）。
"""

import json
from dataclasses import dataclass
from pathlib import Path

from lib.events import sources
from lib.utils.private_data import ensure_dir, require_private_write

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class SourcePaths:
    toggl_entries: Path
    toggl_pushed: Path
    exercise: Path
    sleep: Path
    habitica_history: Path

    @classmethod
    def default(cls, root: Path = REPO_ROOT) -> 'SourcePaths':
        data = root / 'data'
        return cls(
            toggl_entries=data / 'toggl' / 'time_entries.csv',
            toggl_pushed=data / 'toggl' / 'pushed.csv',
            exercise=data / 'googlehealth' / 'exercise.csv',
            sleep=data / 'wearable' / 'sleep.csv',
            habitica_history=data / 'habitica' / 'history.csv',
        )


def collect(paths: SourcePaths) -> dict[str, list[dict]]:
    """期待するソース名 → イベントのリスト。キーの集合が「期待するソース」"""
    return {
        'toggl': sources.toggl_events(paths.toggl_entries, paths.toggl_pushed),
        'googlehealth_exercise': sources.exercise_events(paths.exercise),
        'wearable_sleep': sources.sleep_events(paths.sleep),
        'habitica': sources.habitica_events(paths.habitica_history),
    }


def empty_sources(by_source: dict[str, list[dict]]) -> list[str]:
    return [name for name, events in by_source.items() if not events]


def merge(by_source: dict[str, list[dict]]) -> list[dict]:
    """全ソースを start 昇順に並べる。同時刻は source, name で安定させる"""
    events = [e for events in by_source.values() for e in events]
    return sorted(events, key=lambda e: (e['start'], e['source'], e['name']))


def to_line(event: dict) -> str:
    end = event['end']
    return json.dumps({
        'start': event['start'].isoformat(),
        'end': end.isoformat() if end is not None else None,
        'source': event['source'],
        'kind': event['kind'],
        'name': event['name'],
        'attrs': event['attrs'],
    }, ensure_ascii=False)


def write_jsonl(events: list[dict], out_path: Path) -> None:
    """全上書き。途中で落ちても半端なファイルを残さないよう一時ファイル経由で置き換える"""
    require_private_write(out_path)
    ensure_dir(out_path.parent)
    tmp = out_path.with_name(out_path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        for event in events:
            f.write(to_line(event) + '\n')
    tmp.replace(out_path)
