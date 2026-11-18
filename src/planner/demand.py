"""Demand-gap model: which city pairs have high potential demand but weak or no direct service?

Demand potential uses a gravity model, the standard first-pass estimate in transport planning:

    index = P_a * P_b / d^beta

with P the city population, d the straight-line distance and beta = 2. It is a ranking signal,
not a passenger forecast: there is no ticket data in a public feed. ``calibrate`` reports how well
the index explains today's service levels, so a planner can judge how far to trust it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    EUROPE_EAST,
    EXCLUDED_COUNTRIES,
    EXCLUDED_REGIONS,
    GRAVITY_MAX_KM,
    GRAVITY_MIN_KM,
    GRAVITY_MIN_POP,
    LOW_FREQUENCY_WEEKLY,
    MERGE_RADIUS_KM,
)
from .geo import haversine_km

BETA = 2.0
# "Linked via hub (untimed)" only means some city has direct trips to both ends; the top
# opportunities are then checked against the timetable in transfers.refine().
STATUS_ORDER = ["No service: city not on network", "No direct service", "Linked via hub (untimed)",
                "Low frequency", "Served"]


def eligible_cities(cities: pd.DataFrame, min_pop: int = GRAVITY_MIN_POP) -> pd.DataFrame:
    """Cities that can be an end of a candidate line.

    Drops excluded countries and regions, then merges city districts (cities within
    MERGE_RADIUS_KM of a larger one) into the larger city.
    """
    c = cities[~cities["country"].isin(EXCLUDED_COUNTRIES)].copy()
    excluded = c.apply(lambda r: r["admin1"] in EXCLUDED_REGIONS.get(r["country"], {}), axis=1) \
        if "admin1" in c.columns else pd.Series(False, index=c.index)
    c = c[~excluded]
    c = c[c["population"] >= min_pop].sort_values("population", ascending=False).reset_index(drop=True)
    keep: list[int] = []
    for i, row in c.iterrows():
        if keep:
            k = c.loc[keep]
            if (haversine_km(row["lat"], row["lon"], k["lat"].to_numpy(), k["lon"].to_numpy()) < MERGE_RADIUS_KM).any():
                continue
        keep.append(i)
    return c.loc[keep].reset_index(drop=True)


def candidate_pairs(cities: pd.DataFrame, min_pop: int = GRAVITY_MIN_POP,
                    min_km: float = GRAVITY_MIN_KM, max_km: float = GRAVITY_MAX_KM) -> pd.DataFrame:
    """City pairs with at least one end in Europe East and a plausible coach distance."""
    big = eligible_cities(cities, min_pop)
    east = big[big["country"].isin(EUROPE_EAST)]
    a = east.add_prefix("a_").assign(k=1)
    b = big.add_prefix("b_").assign(k=1)
    p = a.merge(b, on="k").drop(columns="k")
    p = p[p["a_geonameid"] != p["b_geonameid"]]
    # Keep each unordered pair once: if both are Europe East, keep the lexicographically smaller id first.
    both_east = p["b_country"].isin(EUROPE_EAST)
    p = p[~both_east | (p["a_geonameid"] < p["b_geonameid"])]
    p["km"] = haversine_km(p["a_lat"], p["a_lon"], p["b_lat"], p["b_lon"])
    p = p[(p["km"] >= min_km) & (p["km"] <= max_km)].copy()
    p["gravity"] = (p["a_population"].astype(float) * p["b_population"]) / p["km"] ** BETA
    p["demand_index"] = (100 * p["gravity"] / p["gravity"].max()).round(2)
    p["a"] = "gn:" + p["a_geonameid"]
    p["b"] = "gn:" + p["b_geonameid"]
    keep = ["a", "a_name", "a_country", "a_population", "a_lat", "a_lon",
            "b", "b_name", "b_country", "b_population", "b_lat", "b_lon", "km", "demand_index"]
    return p[keep].sort_values("demand_index", ascending=False).reset_index(drop=True)


def classify(cands: pd.DataFrame, pairs: pd.DataFrame, places: pd.DataFrame) -> pd.DataFrame:
    """Attach today's service level to every candidate pair."""
    key = lambda x, y: tuple(sorted((x, y)))  # noqa: E731
    served = {key(a, b): (w, m) for a, b, w, m in
              zip(pairs["a"], pairs["b"], pairs["weekly_departures"], pairs["fastest_min"])}
    neighbours: dict[str, set] = {}
    for a, b in zip(pairs["a"], pairs["b"]):
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    on_network = set(places["place_id"])

    status, weekly, fastest, via = [], [], [], []
    for a, b in zip(cands["a"], cands["b"]):
        w, m = served.get(key(a, b), (0, np.nan))
        hubs = neighbours.get(a, set()) & neighbours.get(b, set())
        if a not in on_network or b not in on_network:
            s = STATUS_ORDER[0]
        elif w == 0 and not hubs:
            s = STATUS_ORDER[1]
        elif w == 0:
            s = STATUS_ORDER[2]
        elif w < LOW_FREQUENCY_WEEKLY:
            s = STATUS_ORDER[3]
        else:
            s = STATUS_ORDER[4]
        status.append(s)
        weekly.append(int(w))
        fastest.append(m)
        via.append(len(hubs))
    out = cands.assign(status=status, weekly_departures=weekly, fastest_min=fastest, transfer_hubs=via)
    out["cross_border"] = out["a_country"] != out["b_country"]
    return out


def calibrate(classified: pd.DataFrame) -> dict:
    """Spearman rank correlation between demand index and today's weekly departures (served pairs)."""
    s = classified[classified["weekly_departures"] > 0]
    if len(s) < 3:
        return {"served_pairs": int(len(s)), "spearman": None}
    rho = s["demand_index"].rank().corr(s["weekly_departures"].rank())
    return {"served_pairs": int(len(s)), "spearman": round(float(rho), 3)}


def opportunities(classified: pd.DataFrame, top: int = 50) -> pd.DataFrame:
    """Highest-potential pairs that are not served directly, or only weakly."""
    gaps = classified[classified["status"] != "Served"].copy()
    gaps["rank"] = gaps["demand_index"].rank(ascending=False, method="first").astype(int)
    return gaps.sort_values("rank").head(top).reset_index(drop=True)


def unserved_cities(cities: pd.DataFrame, places: pd.DataFrame, min_pop: int = GRAVITY_MIN_POP) -> pd.DataFrame:
    big = eligible_cities(cities, min_pop)
    big = big[big["country"].isin(EUROPE_EAST)]
    out = big[~("gn:" + big["geonameid"]).isin(places["place_id"])]
    return out[["name", "country", "population", "lat", "lon"]].sort_values("population", ascending=False) \
        .reset_index(drop=True)
