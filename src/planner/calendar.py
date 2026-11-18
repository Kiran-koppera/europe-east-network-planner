"""Which services run on which days."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from .gtfs import Feed

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y%m%d").date()


def reference_week(feed: Feed) -> tuple[date, date]:
    """First full Monday-Sunday week starting at least 7 days after the feed starts.

    Avoids the partial first days of a feed, when some services are not loaded yet.
    """
    start = feed.feed_info.get("feed_start_date")
    if start:
        d0 = parse_date(start) + timedelta(days=7)
    else:
        cal = feed["calendar"]
        d0 = parse_date(cal["start_date"].min()) if len(cal) else date.today()
    monday = d0 + timedelta(days=(7 - d0.weekday()) % 7)
    return monday, monday + timedelta(days=6)


def active_days(feed: Feed, first: date, last: date) -> pd.Series:
    """Number of days in [first, last] on which each service_id runs."""
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    active: dict[str, set] = {}

    cal = feed["calendar"]
    if len(cal):
        starts = cal["start_date"].map(parse_date)
        ends = cal["end_date"].map(parse_date)
        for d in days:
            col = WEEKDAYS[d.weekday()]
            mask = (cal[col] == "1") & (starts <= d) & (ends >= d)
            for sid in cal.loc[mask, "service_id"]:
                active.setdefault(sid, set()).add(d)

    cd = feed["calendar_dates"]
    if len(cd):
        cd = cd.assign(d=cd["date"].map(parse_date))
        cd = cd[(cd["d"] >= first) & (cd["d"] <= last)]
        for sid, d, kind in zip(cd["service_id"], cd["d"], cd["exception_type"]):
            if kind == "1":
                active.setdefault(sid, set()).add(d)
            elif kind == "2":
                active.get(sid, set()).discard(d)

    return pd.Series({sid: len(ds) for sid, ds in active.items()}, dtype="int64", name="days")
