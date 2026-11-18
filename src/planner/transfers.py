"""Timed transfer check: can a passenger actually change between two buses?

"Transfer only" in the demand model means some city has direct trips to both ends. That is a
topology statement. This module checks the timetable: on each date of the reference week, does
a first leg arrive at the hub early enough (MIN_TRANSFER) but not too early (MAX_WAIT) before a
second leg leaves for the destination? Trip dates are taken from the calendar, so overnight
trips (times past 24:00) and trips that do not run on a given day are handled correctly.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .calendar import parse_date
from .gtfs import Feed

MIN_TRANSFER_MIN = 15
MAX_WAIT_MIN = 180


def service_dates(feed: Feed, first: date, last: date) -> dict[str, set[date]]:
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    out: dict[str, set[date]] = {}
    cal = feed["calendar"]
    cols = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if len(cal):
        starts, ends = cal["start_date"].map(parse_date), cal["end_date"].map(parse_date)
        for d in days:
            m = (cal[cols[d.weekday()]] == "1") & (starts <= d) & (ends >= d)
            for sid in cal.loc[m, "service_id"]:
                out.setdefault(sid, set()).add(d)
    cd = feed["calendar_dates"]
    if len(cd):
        cd = cd.assign(d=cd["date"].map(parse_date))
        for sid, d, kind in zip(cd["service_id"], cd["d"], cd["exception_type"]):
            if first <= d <= last:
                (out.setdefault(sid, set()).add(d) if kind == "1" else out.get(sid, set()).discard(d))
    return out


def timed_legs(feed: Feed, stop_places: pd.DataFrame, first: date, last: date, places: set[str]) -> pd.DataFrame:
    """Place-to-place legs touching `places`, with absolute times (seconds since `first` 00:00)."""
    dates = service_dates(feed, first, last)
    trips = feed["trips"][["trip_id", "service_id", "route_id"]]
    trips = trips[trips["service_id"].isin(dates)]
    st = feed["stop_times"][["trip_id", "stop_id", "stop_sequence", "arr_s", "dep_s"]]
    st = st[st["trip_id"].isin(trips["trip_id"])].merge(stop_places[["stop_id", "place_id", "stop_name"]], on="stop_id")
    keep = set(st.loc[st["place_id"].isin(places), "trip_id"])
    st = st[st["trip_id"].isin(keep)]
    a = st.rename(columns={"place_id": "o", "stop_sequence": "so", "dep_s": "dep", "stop_name": "o_stop"})
    b = st.rename(columns={"place_id": "d", "stop_sequence": "sd", "arr_s": "arr", "stop_name": "d_stop"})
    legs = a[["trip_id", "o", "so", "dep", "o_stop"]].merge(b[["trip_id", "d", "sd", "arr", "d_stop"]], on="trip_id")
    legs = legs[(legs["sd"] > legs["so"]) & (legs["o"] != legs["d"])]
    legs = legs[legs["o"].isin(places) | legs["d"].isin(places)]
    legs = legs.merge(trips, on="trip_id")
    rows = []
    for r in legs.itertuples():
        for d in dates[r.service_id]:
            off = (d - first).days * 86400
            rows.append((r.trip_id, r.route_id, d, r.o, r.d, r.o_stop, r.d_stop, off + r.dep, off + r.arr))
    return pd.DataFrame(rows, columns=["trip_id", "route_id", "date", "o", "d", "o_stop", "d_stop", "dep", "arr"])


def connections(legs: pd.DataFrame, origin: str, dest: str, hubs: list[str] | None = None,
                min_transfer: int = MIN_TRANSFER_MIN, max_wait: int = MAX_WAIT_MIN,
                last_start: date | None = None) -> pd.DataFrame:
    """All feasible one-change itineraries origin -> hub -> dest that start within the week."""
    first = legs[(legs["o"] == origin) & (legs["d"] != dest)]
    if last_start is not None:
        first = first[first["date"] <= last_start]
    second = legs[(legs["d"] == dest) & (legs["o"] != origin)]
    if hubs is not None:
        first, second = first[first["d"].isin(hubs)], second[second["o"].isin(hubs)]
    m = first.merge(second, left_on="d", right_on="o", suffixes=("_1", "_2"))
    wait = (m["dep_2"] - m["arr_1"]) / 60
    m = m[(wait >= min_transfer) & (wait <= max_wait) & (m["trip_id_1"] != m["trip_id_2"])].copy()
    m["wait_min"] = ((m["dep_2"] - m["arr_1"]) / 60).round().astype(int)
    m["total_min"] = ((m["arr_2"] - m["dep_1"]) / 60).round().astype(int)
    m["hub"] = m["d_1"]
    # Keep the fastest itinerary per first departure (a passenger takes the first good connection).
    m = m.sort_values("total_min").drop_duplicates(["trip_id_1", "date_1"])
    return m.sort_values(["date_1", "dep_1"]).reset_index(drop=True)


def direct(legs: pd.DataFrame, origin: str, dest: str) -> pd.DataFrame:
    d = legs[(legs["o"] == origin) & (legs["d"] == dest)].copy()
    d["total_min"] = ((d["arr"] - d["dep"]) / 60).round().astype(int)
    return d


def summarize(conn: pd.DataFrame) -> dict:
    if conn.empty:
        return {"weekly_itineraries": 0, "days_with_connection": 0, "best_total_min": None, "best_hub": None,
                "median_total_min": None}
    best = conn.loc[conn["total_min"].idxmin()]
    return {"weekly_itineraries": int(len(conn)), "days_with_connection": int(conn["date_1"].nunique()),
            "best_total_min": int(best["total_min"]), "best_hub": best["hub"],
            "median_total_min": int(conn["total_min"].median())}


PRACTICAL_FACTOR = 2.0       # a transfer is practical if it takes at most 2x the direct coach time ...
PRACTICAL_ALLOWANCE_MIN = 60  # ... plus one hour for the change


def practical_limit(km: float) -> float:
    from .config import COACH_SPEED_KMH, ROAD_FACTOR
    return PRACTICAL_FACTOR * km * ROAD_FACTOR / COACH_SPEED_KMH * 60 + PRACTICAL_ALLOWANCE_MIN


def refine(opps: pd.DataFrame, feed: Feed, stop_places: pd.DataFrame, pairs: pd.DataFrame,
           places: pd.DataFrame, week: tuple[date, date]) -> pd.DataFrame:
    """Replace the untimed hub status of each opportunity with a timetable verdict."""
    nb: dict[str, set] = {}
    for a, b in zip(pairs["a"], pairs["b"]):
        nb.setdefault(a, set()).add(b)
        nb.setdefault(b, set()).add(a)
    name = places.set_index("place_id")["place"]
    out = opps.copy()
    for c in ["practical_ab", "practical_ba", "best_ab_min", "best_ba_min"]:
        out[c] = pd.NA
    out["best_ab_hub"], out["best_ba_hub"] = None, None
    todo = out.index[out["status"] == "Linked via hub (untimed)"]
    if len(todo) == 0:
        return out
    need = set(out.loc[todo, "a"]) | set(out.loc[todo, "b"])
    legs = timed_legs(feed, stop_places, week[0], week[1] + timedelta(days=1), need)
    for i in todo:
        a, b, km = out.at[i, "a"], out.at[i, "b"], out.at[i, "km"]
        hubs = sorted(nb.get(a, set()) & nb.get(b, set()))
        limit = practical_limit(km)
        for tag, (o, d) in {"ab": (a, b), "ba": (b, a)}.items():
            c = connections(legs, o, d, hubs, last_start=week[1])
            ok = c[c["total_min"] <= limit]
            out.at[i, f"practical_{tag}"] = int(len(ok))
            best = ok if len(ok) else c
            if len(best):
                row = best.loc[best["total_min"].idxmin()]
                out.at[i, f"best_{tag}_min"] = int(row["total_min"])
                out.at[i, f"best_{tag}_hub"] = name.get(row["hub"], row["hub"])
        n_ab, n_ba = out.at[i, "practical_ab"], out.at[i, "practical_ba"]
        out.at[i, "status"] = ("Practical transfer" if n_ab and n_ba else
                               "Practical transfer (one direction)" if n_ab or n_ba else "No practical transfer")
    return out
