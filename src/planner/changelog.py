"""Week-over-week network changelog.

Each run saves a compact, gzipped snapshot with weekly departures for 8 consecutive calendar
weeks, per place and per direct city pair touching Europe East. The diff compares the current
feed's reference week with the *same calendar week* in the previous snapshot. Comparing each
feed's own first week instead would turn seasonal differences between two weeks into fake
network changes, because every new feed starts a week later.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd

FREQ_CHANGE_MIN = 7  # ignore changes smaller than one departure per day
SUMMARY_KEYS = ["places_added", "places_removed", "stops_added", "stops_removed", "pairs_added", "pairs_removed",
                "frequency_up", "frequency_down"]
EVENT = {"places_added": "place_added", "places_removed": "place_removed", "stops_added": "stop_added",
         "stops_removed": "stop_removed", "pairs_added": "pair_added", "pairs_removed": "pair_removed",
         "frequency_up": "frequency_up", "frequency_down": "frequency_down"}


def snapshot(feed_meta: dict, weeks: list[str], place_names: pd.DataFrame,
             place_weekly: pd.DataFrame, pair_weekly: pd.DataFrame,
             stop_weekly: pd.DataFrame | None = None, stop_places: pd.DataFrame | None = None) -> dict:
    names = place_names.set_index("place_id")
    sp = stop_places.set_index("stop_id") if stop_places is not None else None
    return {
        "version": 2,
        "meta": feed_meta,
        "weeks": weeks,
        "places": {pid: [names.at[pid, "place"] if pid in names.index else pid,
                         names.at[pid, "country"] if pid in names.index else "",
                         [int(v) for v in row]] for pid, row in place_weekly.iterrows()},
        "pairs": {k: [int(v) for v in row] for k, row in pair_weekly.iterrows() if row.any()},
        "stops": {} if stop_weekly is None else {
            sid: [sp.at[sid, "stop_name"], sp.at[sid, "place"], [int(v) for v in row]]
            for sid, row in stop_weekly.iterrows() if row.any()},
    }


def save_snapshot(snap: dict, history_dir: Path) -> Path:
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"{snap['meta']['snapshot_date']}.json.gz"
    raw = json.dumps(snap, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")
    path.write_bytes(gzip.compress(raw, mtime=0))  # mtime=0: identical data gives identical bytes
    return path


def previous_snapshot(history_dir: Path, current_date: str) -> dict | None:
    """Latest earlier snapshot in the current format (older formats are skipped)."""
    for path in sorted((p for p in history_dir.glob("*.json.gz") if p.name.split(".")[0] < current_date),
                       reverse=True):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            snap = json.load(f)
        if snap.get("version") == 2:
            return snap
    return None


def _week_values(snap: dict, week: str, table: str) -> dict:
    i = snap["weeks"].index(week)
    if table in ("places", "stops"):
        return {k: v[2][i] for k, v in snap.get(table, {}).items() if v[2][i] > 0}
    return {k: v[i] for k, v in snap["pairs"].items() if v[i] > 0}


def diff(prev: dict | None, curr: dict, week: str | None = None) -> dict:
    week = week or curr["weeks"][0]
    base = {"from": prev["meta"]["snapshot_date"] if prev else None, "to": curr["meta"]["snapshot_date"],
            "week": week, "events": [], "summary": dict.fromkeys(SUMMARY_KEYS, 0)}
    if prev is None:
        return {**base, "baseline": True, "comparable": False}
    if week not in prev["weeks"]:
        return {**base, "baseline": False, "comparable": False,
                "note": f"Previous snapshot does not cover the week of {week}."}

    names = {**{k: v[0] for k, v in prev["places"].items()}, **{k: v[0] for k, v in curr["places"].items()}}
    country = {**{k: v[1] for k, v in prev["places"].items()}, **{k: v[1] for k, v in curr["places"].items()}}
    label = lambda key: " – ".join(names.get(p, p) for p in key.split("|"))  # noqa: E731
    pp, cp = _week_values(prev, week, "places"), _week_values(curr, week, "places")
    pa, ca = _week_values(prev, week, "pairs"), _week_values(curr, week, "pairs")
    ps, cs = _week_values(prev, week, "stops"), _week_values(curr, week, "stops")
    stop_name = {**{k: v for k, v in prev.get("stops", {}).items()}, **curr.get("stops", {})}

    events = [{"type": "place_added", "item": names[k], "country": country[k], "to": cp[k]}
              for k in cp.keys() - pp.keys()]
    events += [{"type": "place_removed", "item": names[k], "country": country[k], "from": pp[k]}
               for k in pp.keys() - cp.keys()]
    if prev.get("stops"):  # stop-level events need both snapshots to carry stops
        events += [{"type": "stop_added", "item": f"{stop_name[k][0]} ({stop_name[k][1]})", "key": k, "to": cs[k]}
                   for k in cs.keys() - ps.keys()]
        events += [{"type": "stop_removed", "item": f"{stop_name[k][0]} ({stop_name[k][1]})", "key": k, "from": ps[k]}
                   for k in ps.keys() - cs.keys()]
    events += [{"type": "pair_added", "item": label(k), "key": k, "to": ca[k]} for k in ca.keys() - pa.keys()]
    events += [{"type": "pair_removed", "item": label(k), "key": k, "from": pa[k]} for k in pa.keys() - ca.keys()]
    for k in ca.keys() & pa.keys():
        delta = ca[k] - pa[k]
        if abs(delta) >= FREQ_CHANGE_MIN:
            events.append({"type": "frequency_up" if delta > 0 else "frequency_down", "item": label(k), "key": k,
                           "from": pa[k], "to": ca[k]})
    summary = {k: sum(e["type"] == EVENT[k] for e in events) for k in SUMMARY_KEYS}
    order = {t: i for i, t in enumerate(EVENT.values())}
    events.sort(key=lambda e: (order[e["type"]], -abs(e.get("to", 0) - e.get("from", 0)), e["item"]))
    return {**base, "baseline": False, "comparable": True, "events": events, "summary": summary}
