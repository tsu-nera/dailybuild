"""HA の state 履歴を時系列に読む部品（観察日記と早起きの lap が共有する）"""

import datetime as dt

from lib.clients.homeassistant_client import HomeAssistantClient, load_settings

JST = dt.timezone(dt.timedelta(hours=9))
NO_DATA = ('unavailable', 'unknown')


def fetch_history(start: dt.datetime, end: dt.datetime, entity_ids) -> dict[str, list[tuple]]:
    """{entity_id: [(時刻, state, 窓の開始時点の値か)]}。変化時刻は last_changed"""
    url, token = load_settings()
    raw = HomeAssistantClient(url, token).history_during_period(start, end, list(entity_ids))
    out = {}
    for eid, rows in raw.items():
        series = []
        for i, r in enumerate(rows):
            ts = r.get('lc', r['lu'])
            t = dt.datetime.fromtimestamp(ts, JST)
            series.append((t, r['s'], i == 0 and t <= start))
        out[eid] = series
    return out


def last_seen(hist, entity_ids) -> dt.datetime | None:
    """entity 群から最後に何かが届いた時刻。Companion App が止まると値は最後のまま残り、
    画面 on が窓の終わりまで続いたように見える（2026-10-15 夜から止まって 593分と出た）"""
    seen = [t for eid in entity_ids for t, s, initial in hist.get(eid, ()) if not initial]
    return max(seen) if seen else None


def noise_bursts(series, loud_dbfs: float, gap: dt.timedelta) -> list[tuple]:
    """loud_dbfs 以上の分を gap 以内でつないだ塊 [(開始, 終了, max)]"""
    out = []
    for t, s, _ in series:
        try:
            v = float(s)
        except ValueError:
            continue
        if v < loud_dbfs:
            continue
        if out and t - out[-1][1] <= gap:
            out[-1][1], out[-1][2] = t, max(out[-1][2], v)
        else:
            out.append([t, t, v])
    return [tuple(b) for b in out]


def numeric(series) -> list[tuple]:
    out = []
    for t, s, _ in series:
        try:
            out.append((t, float(s)))
        except ValueError:
            continue
    return out


def collapse(times: list[dt.datetime], within: dt.timedelta) -> list[dt.datetime]:
    """照明3灯のように同時に変わる複数 entity の変化を1回にまとめる"""
    out = []
    for t in sorted(times):
        if not out or t - out[-1] > within:
            out.append(t)
    return out
