"""Command line.

    python -m planner download          # fetch the feed and the GeoNames city list into data/raw
    python -m planner run               # full pipeline -> output/
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from .config import FEED_URL, GEONAMES_URL
from .pipeline import ROOT, Paths, run

RAW = ROOT / "data" / "raw"


def download() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for url, name in [(FEED_URL, "gtfs_generic_eu.zip"), (GEONAMES_URL, "cities15000.zip")]:
        req = urllib.request.Request(url, headers={"User-Agent": "europe-east-network-planner"})
        with urllib.request.urlopen(req, timeout=120) as r, (RAW / name).open("wb") as f:
            f.write(r.read())
        print(f"downloaded {name}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="planner", description="Europe East coach network planner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download")
    r = sub.add_parser("run")
    r.add_argument("--feed", type=Path, default=RAW / "gtfs_generic_eu.zip")
    r.add_argument("--cities", type=Path, default=RAW / "cities15000.zip")
    r.add_argument("--out", type=Path, default=ROOT / "output")
    r.add_argument("--history", type=Path, default=ROOT / "data" / "history")
    r.add_argument("--date", help="snapshot date (YYYY-MM-DD), default today")
    a = ap.parse_args()
    if a.cmd == "download":
        download()
        return
    res = run(Paths(a.feed, a.cities, a.out, a.history), a.date)
    print(json.dumps(res["metrics"], indent=2, default=str))
    if res["dossier"]:
        print("dossier:", res["dossier"])


if __name__ == "__main__":
    main()
