"""Load a GTFS feed from a .zip or a directory into DataFrames."""
from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REQUIRED = {
    "agency": ["agency_id", "agency_name"],
    "stops": ["stop_id", "stop_name", "stop_lat", "stop_lon"],
    "routes": ["route_id", "route_type"],
    "trips": ["route_id", "trip_id", "service_id"],
    "stop_times": ["trip_id", "stop_id", "arrival_time", "departure_time", "stop_sequence"],
}
OPTIONAL = ["calendar", "calendar_dates", "feed_info"]
SKIP = {"shapes"}  # large and not needed for network analysis


@dataclass
class Feed:
    tables: dict[str, pd.DataFrame]
    missing: list[str] = field(default_factory=list)
    sha256: str = ""

    def __getitem__(self, name: str) -> pd.DataFrame:
        return self.tables.get(name, pd.DataFrame())

    @property
    def feed_info(self) -> dict:
        fi = self["feed_info"]
        return fi.iloc[0].to_dict() if len(fi) else {}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_feed(path: str | Path) -> Feed:
    path = Path(path)
    tables: dict[str, pd.DataFrame] = {}
    if path.is_dir():
        files = {p.stem: p for p in path.glob("*.txt")}
        opener = lambda name: files[name].open("rb")  # noqa: E731
        names = set(files)
        digest = ""
    else:
        zf = zipfile.ZipFile(path)
        names = {Path(n).stem for n in zf.namelist() if n.endswith(".txt")}
        member = {Path(n).stem: n for n in zf.namelist()}
        opener = lambda name: zf.open(member[name])  # noqa: E731
        digest = _sha256(path)

    for name in sorted(names - SKIP):
        with opener(name) as fh:
            tables[name] = pd.read_csv(fh, dtype=str, keep_default_na=False)

    missing = [n for n in REQUIRED if n not in tables]
    if "calendar" not in tables and "calendar_dates" not in tables:
        missing.append("calendar|calendar_dates")
    _coerce(tables)
    return Feed(tables=tables, missing=missing, sha256=digest)


def _coerce(t: dict[str, pd.DataFrame]) -> None:
    if "stops" in t:
        for c in ("stop_lat", "stop_lon"):
            t["stops"][c] = pd.to_numeric(t["stops"][c], errors="coerce")
    if "stop_times" in t:
        st = t["stop_times"]
        st["stop_sequence"] = pd.to_numeric(st["stop_sequence"], errors="coerce")
        st["arr_s"] = st["arrival_time"].map(to_seconds)
        st["dep_s"] = st["departure_time"].map(to_seconds)
    if "routes" in t:
        t["routes"]["route_type"] = pd.to_numeric(t["routes"]["route_type"], errors="coerce")


def to_seconds(value: str) -> float:
    """GTFS times may exceed 24:00:00 for trips running past midnight."""
    try:
        h, m, s = value.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return float("nan")
