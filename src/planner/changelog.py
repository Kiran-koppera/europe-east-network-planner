"""Week-over-week network changelog.

Each run saves a compact, gzipped snapshot: every place with its weekly departures, and every
direct city pair that touches Europe East with its weekly departures. Comparing two snapshots
shows new or dropped places, new or dropped direct connections, and frequency changes.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd

FREQ_CHANGE_MIN = 7  # ignore changes smaller than one departure per day


def snapshot(feed_meta: dict, places: pd.DataFrame, pairs: pd.DataFrame) -> dict:
    ee = pairs[pairs["europe_east"]] if "europe_east" in pairs else pairs
    return {
        "meta": feed_meta,
        "places": {r.place_id: [r.place, r.country, int(r.weekly_departures)] for r in places.itertuples()},
        "pairs": {f"{r.a}|{r.b}": int(r.weekly_departures) for r in ee.itertuples()},
    }


def save_snapshot(snap: dict, history_dir: Path) -> Path:
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"{snap['meta']['snapshot_date']}.json.gz"
    raw = json.dumps(snap, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")
    path.write_bytes(gzip.compress(raw, mtime=0))  # mtime=0: identical data gives identical bytes
    return path


def previous_snapshot(history_dir: Path, current_date: str) -> dict | None:
    files = sorted(p for p in history_dir.glob("*.json.gz") if p.name.split(".")[0] < current_date)
    if not files:
        return None
    with gzip.open(files[-1], "rt", encoding="utf-8") as f:
        return json.load(f)


def diff(prev: dict | None, curr: dict) -> dict:
    empty = {"places_added": 0, "places_removed": 0, "pairs_added": 0, "pairs_removed": 0,
             "frequency_up": 0, "frequency_down": 0}
    if prev is None:
        return {"baseline": True, "from": None, "to": curr["meta"]["snapshot_date"], "events": [], "summary": empty}
    names = {**{k: v[0] for k, v in prev["places"].items()}, **{k: v[0] for k, v in curr["places"].items()}}
    label = lambda key: " – ".join(names.get(p, p) for p in key.split("|"))  # noqa: E731
    events = []
    pp, cp = prev["places"], curr["places"]
    events += [{"type": "place_added", "item": cp[k][0], "country": cp[k][1]} for k in cp.keys() - pp.keys()]
    events += [{"type": "place_removed", "item": pp[k][0], "country": pp[k][1]} for k in pp.keys() - cp.keys()]
    pa, ca = prev["pairs"], curr["pairs"]
    events += [{"type": "pair_added", "item": label(k), "weekly": ca[k]} for k in ca.keys() - pa.keys()]
    events += [{"type": "pair_removed", "item": label(k), "weekly": pa[k]} for k in pa.keys() - ca.keys()]
    for k in ca.keys() & pa.keys():
        delta = ca[k] - pa[k]
        if abs(delta) >= FREQ_CHANGE_MIN:
            events.append({"type": "frequency_up" if delta > 0 else "frequency_down", "item": label(k),
                           "from": pa[k], "to": ca[k]})
    summary = {"places_added": sum(e["type"] == "place_added" for e in events),
               "places_removed": sum(e["type"] == "place_removed" for e in events),
               "pairs_added": sum(e["type"] == "pair_added" for e in events),
               "pairs_removed": sum(e["type"] == "pair_removed" for e in events),
               "frequency_up": sum(e["type"] == "frequency_up" for e in events),
               "frequency_down": sum(e["type"] == "frequency_down" for e in events)}
    return {"baseline": False, "from": prev["meta"]["snapshot_date"], "to": curr["meta"]["snapshot_date"],
            "events": sorted(events, key=lambda e: (e["type"], e["item"])), "summary": summary}
