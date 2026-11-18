"""Data-quality checks on a GTFS feed.

Each check returns how many records fail, a severity, and a few example IDs, so a planner can
find the record in the source system and fix it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .calendar import parse_date
from .config import MAX_BUS_SPEED_KMH, MAX_TRAIN_SPEED_KMH
from .geo import haversine_km
from .gtfs import REQUIRED, Feed

ERROR, WARNING = "error", "warning"


@dataclass
class Check:
    id: str
    title: str
    severity: str
    checked: int
    failed: int
    examples: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict:
        return {**asdict(self), "passed": self.passed}


def _ex(values, n: int = 5) -> list[str]:
    return [str(v) for v in list(dict.fromkeys(values))[:n]]


def run_checks(feed: Feed) -> list[Check]:
    out: list[Check] = []
    add = out.append

    # 1-2. Structure
    add(Check("files", "Required files present", ERROR, len(REQUIRED) + 1, len(feed.missing), feed.missing))
    bad_cols = [f"{t}.{c}" for t, cols in REQUIRED.items() if t in feed.tables
                for c in cols if c not in feed[t].columns]
    add(Check("columns", "Required columns present",
              ERROR, sum(len(c) for c in REQUIRED.values()), len(bad_cols), bad_cols))
    if feed.missing or bad_cols:
        return out  # content checks are meaningless until the structure is fixed

    stops, trips, st, routes = feed["stops"], feed["trips"], feed["stop_times"], feed["routes"]
    cal, cd = feed["calendar"], feed["calendar_dates"]

    # 3-4. Stops
    bad_coord = stops[stops["stop_lat"].isna() | stops["stop_lon"].isna()
                      | ~stops["stop_lat"].between(-90, 90) | ~stops["stop_lon"].between(-180, 180)
                      | ((stops["stop_lat"] == 0) & (stops["stop_lon"] == 0))]
    add(Check("stop_coords", "Stops have valid coordinates", ERROR, len(stops), len(bad_coord),
              _ex(bad_coord["stop_id"])))
    dup = stops[stops["stop_id"].duplicated(keep=False)]
    add(Check("stop_id_unique", "Stop IDs are unique", ERROR, len(stops), dup["stop_id"].nunique(),
              _ex(dup["stop_id"])))

    # 5-7. Referential integrity
    unknown_stop = st[~st["stop_id"].isin(stops["stop_id"])]
    add(Check("st_stop_ref", "Stop times reference existing stops", ERROR, len(st), len(unknown_stop),
              _ex(unknown_stop["stop_id"])))
    unknown_trip = st[~st["trip_id"].isin(trips["trip_id"])]
    add(Check("st_trip_ref", "Stop times reference existing trips", ERROR, len(st), len(unknown_trip),
              _ex(unknown_trip["trip_id"])))
    services = set(cal.get("service_id", pd.Series(dtype=str))) | set(cd.get("service_id", pd.Series(dtype=str)))
    bad_trip = trips[~trips["route_id"].isin(routes["route_id"]) | ~trips["service_id"].isin(services)]
    add(Check("trip_refs", "Trips reference existing routes and calendars", ERROR, len(trips), len(bad_trip),
              _ex(bad_trip["trip_id"])))

    # 8-9. Coverage
    used_stops = set(st["stop_id"])
    orphan = stops[~stops["stop_id"].isin(used_stops)]
    add(Check("orphan_stops", "Every stop is served by at least one trip", WARNING, len(stops), len(orphan),
              _ex(orphan["stop_name"])))
    empty_routes = routes[~routes["route_id"].isin(trips["route_id"])]
    add(Check("empty_routes", "Every route has at least one trip", WARNING, len(routes), len(empty_routes),
              _ex(empty_routes["route_id"])))

    # 10-12. Trip shape and timing
    n = st.groupby("trip_id").size()
    short = n[n < 2]
    add(Check("trip_length", "Trips have at least two stops", ERROR, len(n), len(short), _ex(short.index)))

    s = st.sort_values(["trip_id", "stop_sequence"])
    same = s["trip_id"].eq(s["trip_id"].shift())
    prev_dep = s["dep_s"].shift()
    back = s[same & (s["arr_s"] < prev_dep)]
    within = s[s["dep_s"] < s["arr_s"]]
    bad_time = set(back["trip_id"]) | set(within["trip_id"]) | set(s.loc[s["arr_s"].isna() | s["dep_s"].isna(), "trip_id"])
    add(Check("time_order", "Times never go backwards within a trip", ERROR, len(n), len(bad_time),
              _ex(sorted(bad_time))))

    seg = s.assign(prev_stop=s["stop_id"].shift(), prev_dep=prev_dep)[same]
    seg = seg.merge(stops[["stop_id", "stop_lat", "stop_lon"]], on="stop_id")
    seg = seg.merge(stops[["stop_id", "stop_lat", "stop_lon"]].rename(
        columns={"stop_id": "prev_stop", "stop_lat": "plat", "stop_lon": "plon"}), on="prev_stop")
    seg["km"] = haversine_km(seg["plat"], seg["plon"], seg["stop_lat"], seg["stop_lon"])
    seg["h"] = (seg["arr_s"] - seg["prev_dep"]) / 3600
    seg = seg.merge(trips[["trip_id", "route_id"]], on="trip_id").merge(routes[["route_id", "route_type"]], on="route_id")
    limit = np.where(seg["route_type"] == 2, MAX_TRAIN_SPEED_KMH, MAX_BUS_SPEED_KMH)
    # Ignore very short hops: minute-rounded times make their speeds meaningless.
    fast = seg[(seg["km"] > 3) & ((seg["h"] <= 0) | (seg["km"] / seg["h"].where(seg["h"] > 0) > limit))]
    # Report the stop pairs involved: a recurring pair usually means a misplaced stop coordinate.
    names = stops.set_index("stop_id")["stop_name"]
    pairs = (fast["prev_stop"].map(names) + " -> " + fast["stop_id"].map(names)).value_counts()
    add(Check("speed", "Segment speeds are physically plausible", WARNING, len(seg), len(fast),
              [f"{p} ({n} trips)" for p, n in pairs.head(5).items()]))

    # 13-14. Calendars
    if len(cal):
        inverted = cal[cal["end_date"] < cal["start_date"]]
        add(Check("calendar_range", "Calendar end date is not before start date", ERROR, len(cal), len(inverted),
                  _ex(inverted["service_id"])))
        days = cal[["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]]
        no_days = cal[(days == "1").sum(axis=1) == 0]
        added = set(cd.loc[cd.get("exception_type", pd.Series(dtype=str)) == "1", "service_id"]) if len(cd) else set()
        no_days = no_days[~no_days["service_id"].isin(added)]
        add(Check("calendar_days", "Every service runs on at least one day", WARNING, len(cal), len(no_days),
                  _ex(no_days["service_id"])))

    # 15. Feed validity
    fi = feed.feed_info
    expired = 0
    if fi.get("feed_end_date"):
        expired = int(parse_date(fi["feed_end_date"]) < parse_date(fi.get("feed_start_date", fi["feed_end_date"])))
    add(Check("feed_dates", "Feed validity period is consistent", ERROR, 1, expired))
    return out


def scorecard(checks: list[Check]) -> dict:
    rows = sum(c.checked for c in checks)
    failed = sum(c.failed for c in checks)
    return {
        "checks": len(checks),
        "passed": sum(c.passed for c in checks),
        "errors": sum(1 for c in checks if not c.passed and c.severity == ERROR),
        "warnings": sum(1 for c in checks if not c.passed and c.severity == WARNING),
        "records_checked": rows,
        "records_flagged": failed,
        "pass_rate": round(100 * (1 - failed / rows), 3) if rows else 100.0,
        "results": [c.to_dict() for c in checks],
    }
