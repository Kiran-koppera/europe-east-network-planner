"""City-pair network model: who is connected to whom, how often and how fast."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .calendar import active_days
from .config import EUROPE_EAST
from .geo import haversine_km
from .gtfs import Feed


def trip_weekly_runs(feed: Feed, first: date, last: date) -> pd.Series:
    """How many times each trip runs in the reference week."""
    days = active_days(feed, first, last)
    runs = feed["trips"].set_index("trip_id")["service_id"].map(days).fillna(0).astype(int)
    return runs[runs > 0]


def od_legs(feed: Feed, stop_places: pd.DataFrame, runs: pd.Series) -> pd.DataFrame:
    """Every place-to-place journey possible on a single trip (no change of bus).

    Returns one row per (trip, origin place, destination place) with the in-vehicle time.
    """
    st = feed["stop_times"]
    st = st[st["trip_id"].isin(runs.index)][["trip_id", "stop_id", "stop_sequence", "arr_s", "dep_s"]]
    st = st.merge(stop_places[["stop_id", "place_id"]], on="stop_id")
    a = st.rename(columns={"place_id": "o", "stop_sequence": "so", "dep_s": "t_dep"})[["trip_id", "o", "so", "t_dep"]]
    b = st.rename(columns={"place_id": "d", "stop_sequence": "sd", "arr_s": "t_arr"})[["trip_id", "d", "sd", "t_arr"]]
    legs = a.merge(b, on="trip_id")
    legs = legs[(legs["sd"] > legs["so"]) & (legs["o"] != legs["d"])]
    legs["minutes"] = (legs["t_arr"] - legs["t_dep"]) / 60
    # A trip may call twice in one city; keep the fastest leg per trip and place pair.
    legs = legs.sort_values("minutes").drop_duplicates(["trip_id", "o", "d"])
    legs["runs"] = legs["trip_id"].map(runs)
    return legs[["trip_id", "o", "d", "minutes", "runs"]]


def place_table(stop_places: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    places = (stop_places.groupby("place_id")
              .agg(place=("place", "first"), country=("country", "first"), population=("place_pop", "first"),
                   lat=("place_lat", "first"), lon=("place_lon", "first"), stops=("stop_id", "count"))
              .reset_index())
    dep = legs.groupby("o")["runs"].sum()  # departures to any destination (counts each trip once per leg)
    trips_from = legs.drop_duplicates(["trip_id", "o"]).groupby("o")["runs"].sum()
    places["weekly_departures"] = places["place_id"].map(trips_from).fillna(0).astype(int)
    places["direct_destinations"] = places["place_id"].map(legs.groupby("o")["d"].nunique()).fillna(0).astype(int)
    places["europe_east"] = places["country"].isin(EUROPE_EAST)
    del dep
    return places


def city_pairs(legs: pd.DataFrame, places: pd.DataFrame) -> pd.DataFrame:
    """Undirected city pairs with weekly departures (both directions) and fastest time."""
    lo = np.where(legs["o"] < legs["d"], legs["o"], legs["d"])
    hi = np.where(legs["o"] < legs["d"], legs["d"], legs["o"])
    g = (legs.assign(a=lo, b=hi).groupby(["a", "b"])
         .agg(weekly_departures=("runs", "sum"), fastest_min=("minutes", "min"),
              median_min=("minutes", "median"), trips=("trip_id", "nunique"))
         .reset_index())
    p = places.set_index("place_id")
    for side in ("a", "b"):
        g[f"{side}_name"] = g[side].map(p["place"])
        g[f"{side}_country"] = g[side].map(p["country"])
        g[f"{side}_lat"] = g[side].map(p["lat"])
        g[f"{side}_lon"] = g[side].map(p["lon"])
    g["km"] = haversine_km(g["a_lat"], g["a_lon"], g["b_lat"], g["b_lon"]).round(1)
    g["cross_border"] = g["a_country"] != g["b_country"]
    g["europe_east"] = g["a_country"].isin(EUROPE_EAST) | g["b_country"].isin(EUROPE_EAST)
    g["fastest_min"] = g["fastest_min"].round(0)
    g["median_min"] = g["median_min"].round(0)
    return g.sort_values("weekly_departures", ascending=False).reset_index(drop=True)


def country_kpis(places: pd.DataFrame, pairs: pd.DataFrame, legs: pd.DataFrame, stop_places: pd.DataFrame,
                 feed: Feed, runs: pd.Series) -> pd.DataFrame:
    """One row per country: stops, cities, weekly departures, connections and cross-border share."""
    trips = feed["trips"].set_index("trip_id")
    first_stop = (feed["stop_times"].sort_values("stop_sequence").drop_duplicates("trip_id")
                  .set_index("trip_id")["stop_id"])
    origin_country = first_stop.map(stop_places.set_index("stop_id")["country"])
    w = runs.to_frame("runs").assign(country=origin_country.reindex(runs.index).values,
                                     route=trips["route_id"].reindex(runs.index).values)
    rows = []
    for cc, grp in places.groupby("country"):
        if not cc:
            continue
        pp = pairs[(pairs["a_country"] == cc) | (pairs["b_country"] == cc)]
        rows.append({
            "country": cc,
            "europe_east": cc in EUROPE_EAST,
            "stops": int(stop_places["country"].eq(cc).sum()),
            "places_served": int(len(grp)),
            "cities_100k_served": int((grp["population"] >= 100_000).sum()),
            "weekly_trip_departures": int(w.loc[w["country"] == cc, "runs"].sum()),
            "routes_starting": int(w.loc[w["country"] == cc, "route"].nunique()),
            "city_pairs": int(len(pp)),
            "cross_border_pairs": int(pp["cross_border"].sum()),
            "cross_border_share": round(float(pp["cross_border"].mean()) if len(pp) else 0.0, 3),
        })
    return pd.DataFrame(rows).sort_values("weekly_trip_departures", ascending=False).reset_index(drop=True)


def weekly_series(feed: Feed, stop_places: pd.DataFrame, first_monday: date, n_weeks: int = 8):
    """Weekly departures for n consecutive calendar weeks, per place and per Europe East city pair.

    Lets two feed snapshots be compared on the same calendar week, so a seasonal difference
    between two analysis weeks is never mistaken for a network change.
    """
    from datetime import timedelta

    weeks = [first_monday + timedelta(weeks=i) for i in range(n_weeks)]
    per_week = {w: trip_weekly_runs(feed, w, w + timedelta(days=6)) for w in weeks}
    union = pd.Series(1, index=sorted(set().union(*[set(r.index) for r in per_week.values()])))
    legs = od_legs(feed, stop_places, union)
    country = stop_places.drop_duplicates("place_id").set_index("place_id")["country"]
    ee_place = country.isin(EUROPE_EAST)
    lo = np.where(legs["o"] < legs["d"], legs["o"], legs["d"])
    hi = np.where(legs["o"] < legs["d"], legs["d"], legs["o"])
    legs = legs.assign(key=pd.Series(lo, index=legs.index) + "|" + pd.Series(hi, index=legs.index),
                       ee=legs["o"].map(ee_place).fillna(False) | legs["d"].map(ee_place).fillna(False))
    starts = legs.drop_duplicates(["trip_id", "o"])
    pair_cols, place_cols = {}, {}
    for w, runs in per_week.items():
        r = legs["trip_id"].map(runs).fillna(0)
        pair_cols[w] = r[legs["ee"]].groupby(legs.loc[legs["ee"], "key"]).sum()
        place_cols[w] = starts["trip_id"].map(runs).fillna(0).groupby(starts["o"]).sum()
    pairs = pd.DataFrame(pair_cols).fillna(0).astype(int)
    places = pd.DataFrame(place_cols).fillna(0).astype(int)
    st = feed["stop_times"][["trip_id", "stop_id"]].drop_duplicates()
    st = st[st["stop_id"].isin(stop_places.loc[stop_places["country"].isin(EUROPE_EAST), "stop_id"])]
    stops = pd.DataFrame({w: st["trip_id"].map(r).fillna(0).groupby(st["stop_id"]).sum()
                          for w, r in per_week.items()}).fillna(0).astype(int)
    return [w.isoformat() for w in weeks], places, pairs, stops


def stop_weekly_calls(feed: Feed, runs: pd.Series) -> pd.Series:
    """Trips calling at each stop in the reference week."""
    st = feed["stop_times"][["trip_id", "stop_id"]].drop_duplicates()
    st = st[st["trip_id"].isin(runs.index)]
    return st["trip_id"].map(runs).groupby(st["stop_id"]).sum()
