"""End-to-end run: feed -> quality -> network -> demand -> changelog -> reports -> site data."""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import changelog, demand, network, quality, transfers
from .calendar import reference_week
from .config import EUROPE_EAST, TZ_TO_COUNTRY
from .dossier import EU_MEMBERS, write_dossier
from .excel import write_excel
from .geo import assign_places, load_cities
from .gtfs import load_feed
from .tracker import write_tracker

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Paths:
    feed: Path
    cities: Path
    out: Path
    history: Path


def segments(feed, stop_places: pd.DataFrame, runs: pd.Series, places: pd.DataFrame) -> pd.DataFrame:
    """Consecutive place-to-place hops on real trips, with weekly runs: the lines drawn on the map."""
    st = feed["stop_times"]
    st = st[st["trip_id"].isin(runs.index)].sort_values(["trip_id", "stop_sequence"])
    st = st.assign(place=st["stop_id"].map(stop_places.set_index("stop_id")["place_id"]))
    st = st[st["place"] != st.groupby("trip_id")["place"].shift()]  # collapse repeated calls in one city
    nxt = st.groupby("trip_id")["place"].shift(-1)
    seg = pd.DataFrame({"trip_id": st["trip_id"], "a": st["place"], "b": nxt}).dropna()
    lo = np.where(seg["a"] < seg["b"], seg["a"], seg["b"])
    hi = np.where(seg["a"] < seg["b"], seg["b"], seg["a"])
    seg = seg.assign(a=lo, b=hi, runs=seg["trip_id"].map(runs)).groupby(["a", "b"])["runs"].sum().reset_index()
    p = places.set_index("place_id")
    seg["ee"] = seg["a"].map(p["europe_east"]) | seg["b"].map(p["europe_east"])
    return seg


def pick_dossier_pair(opps: pd.DataFrame) -> dict | None:
    on_net = opps[~opps["status"].isin(["No service: city not on network", "Low frequency"])]
    eu_xb = on_net[on_net["cross_border"] & on_net["a_country"].isin(EU_MEMBERS) & on_net["b_country"].isin(EU_MEMBERS)]
    pick = eu_xb if len(eu_xb) else on_net
    return pick.iloc[0].to_dict() if len(pick) else None


def run(paths: Paths, snapshot_date: str | None = None) -> dict:
    t0 = time.time()
    snapshot_date = snapshot_date or date.today().isoformat()
    feed = load_feed(paths.feed)
    checks = quality.run_checks(feed)
    score = quality.scorecard(checks)

    cities = load_cities(paths.cities, set(TZ_TO_COUNTRY.values()))
    stop_places = assign_places(feed["stops"], cities)
    week = reference_week(feed)
    runs = network.trip_weekly_runs(feed, *week)
    legs = network.od_legs(feed, stop_places, runs)
    places = network.place_table(stop_places, legs)
    pairs = network.city_pairs(legs, places)
    kpis = network.country_kpis(places, pairs, legs, stop_places, feed, runs)
    segs = segments(feed, stop_places, runs, places)

    cands = demand.candidate_pairs(cities)
    classified = demand.classify(cands, pairs, places)
    calib = demand.calibrate(classified)
    opps = demand.opportunities(classified, top=50)
    opps = transfers.refine(opps, feed, stop_places, pairs, places, week)
    unserved = demand.unserved_cities(cities, places)

    meta = {**feed.feed_info, "sha256": feed.sha256, "snapshot_date": snapshot_date,
            "reference_week": [week[0].isoformat(), week[1].isoformat()]}
    weeks, place_weekly, pair_weekly, stop_weekly = network.weekly_series(feed, stop_places, week[0], n_weeks=8)
    snap = changelog.snapshot(meta, weeks, places, place_weekly, pair_weekly, stop_weekly, stop_places)
    prev = changelog.previous_snapshot(paths.history, snapshot_date)
    changes = changelog.diff(prev, snap)
    changelog.save_snapshot(snap, paths.history)

    reports = paths.out / "reports"
    pick = pick_dossier_pair(opps)
    stop_weekly = network.stop_weekly_calls(feed, runs)
    dossier_path, case = (write_dossier(pick, places, meta, reports, feed=feed, stop_places=stop_places, week=week,
                                        legs=legs, pairs=pairs, stop_weekly=stop_weekly) if pick else (None, None))

    ee_places = places[places["europe_east"]]
    ee_pairs = pairs[pairs["europe_east"]]
    metrics = {
        "feed": {"stops": int(len(feed["stops"])), "routes": int(len(feed["routes"])),
                 "trips": int(len(feed["trips"])), "stop_times": int(len(feed["stop_times"])),
                 "countries": int(places["country"].replace("", np.nan).nunique())},
        "reference_week": {"trips_running": int(len(runs)), "weekly_trip_departures": int(runs.sum()),
                           "city_pairs": int(len(pairs)), "places": int(len(places))},
        "europe_east": {"countries_served": int(ee_places["country"].nunique()),
                        "stops": int(stop_places["country"].isin(EUROPE_EAST).sum()),
                        "places": int(len(ee_places)),
                        "cities_100k_served": int((ee_places["population"] >= 100_000).sum()),
                        "city_pairs": int(len(ee_pairs)),
                        "cross_border_share": round(float(ee_pairs["cross_border"].mean()), 3),
                        "weekly_trip_departures": int(kpis.loc[kpis["europe_east"], "weekly_trip_departures"].sum())},
        "quality": {k: v for k, v in score.items() if k != "results"},
        "demand": {"candidate_pairs": int(len(classified)), **calib,
                   "status_counts": classified["status"].value_counts().to_dict(),
                   "unserved_cities_100k": int(len(unserved))},
        "changelog": changes["summary"] | {"baseline": changes["baseline"]},
        "runtime_s": None,
    }

    # Reports
    write_excel(reports / "europe-east-network-report.xlsx", {
        "Summary": pd.DataFrame([{"Metric": k, "Value": v} for k, v in _flat(metrics).items()]),
        "Data quality": pd.DataFrame([{**c.to_dict(), "examples": "; ".join(c.examples)} for c in checks]),
        "Country KPIs": kpis,
        "City pairs (EE)": ee_pairs[["a_name", "a_country", "b_name", "b_country", "km", "weekly_departures",
                                     "fastest_min", "cross_border"]],
        "Opportunities": opps[["rank", "a_name", "a_country", "b_name", "b_country", "km", "demand_index",
                               "status", "weekly_departures", "transfer_hubs", "cross_border"]],
        "Unserved cities": unserved,
        "Changelog": pd.DataFrame(changes["events"]) if changes["events"] else pd.DataFrame(
            [{"note": "Baseline snapshot: changes appear from the next weekly run."}]),
    })

    tracker_stats = write_tracker(reports / "data-quality-issue-tracker.xlsx", quality.speed_exceptions(feed),
                                  feed["stops"], meta)
    metrics["quality"]["tracker"] = tracker_stats

    # Site
    site = paths.out / "site"
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(ROOT / "site", site)
    data = site / "data"
    data.mkdir(exist_ok=True)
    p = places.set_index("place_id")
    seg_ee = segs[segs["ee"]]
    used = set(seg_ee["a"]) | set(seg_ee["b"])
    _dump(data / "network.json", {
        "places": [{"id": i, "n": r.place, "c": r.country, "p": int(r.population), "w": int(r.weekly_departures),
                    "d": int(r.direct_destinations), "ee": bool(r.europe_east), "y": round(r.lat, 4), "x": round(r.lon, 4)}
                   for i, r in p.loc[sorted(used)].iterrows()],
        "segments": [[r.a, r.b, int(r.runs)] for r in seg_ee.itertuples()],
    })
    _dump(data / "opportunities.json", opps.replace({np.nan: None}).round(4).to_dict("records"))
    _dump(data / "unserved.json", unserved.round(4).to_dict("records"))
    _dump(data / "countries.json", kpis.to_dict("records"))
    _dump(data / "quality.json", score)
    _dump(data / "changelog.json", changes)
    _dump(data / "top_pairs.json", ee_pairs.head(30)[["a_name", "a_country", "b_name", "b_country", "km",
                                                       "weekly_departures", "fastest_min"]].to_dict("records"))
    metrics["runtime_s"] = round(time.time() - t0, 1)
    meta_out = {"meta": meta, "metrics": metrics,
                "dossier": {"pair": f"{pick['a_name']} – {pick['b_name']}", "file": dossier_path.name} if pick else None}
    _dump(data / "meta.json", meta_out)
    _dump(paths.out / "metrics.json", meta_out)
    if dossier_path:
        shutil.copy(dossier_path, data / dossier_path.name)
        shutil.copy(dossier_path.with_name(dossier_path.stem + "-map.png"), data / (dossier_path.stem + "-map.png"))
    shutil.copy(reports / "europe-east-network-report.xlsx", data / "europe-east-network-report.xlsx")
    shutil.copy(reports / "data-quality-issue-tracker.xlsx", data / "data-quality-issue-tracker.xlsx")
    return meta_out


def _flat(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flat(v, key + "."))
        else:
            out[key] = v
    return out


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str))
