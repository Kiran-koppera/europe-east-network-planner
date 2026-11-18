"""Distances and stop-to-city assignment."""
from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CITY_RADIUS_KM, TOWN_MERGE_KM, TZ_TO_COUNTRY

EARTH_KM = 6371.0088
GEONAMES_COLS = ["geonameid", "name", "asciiname", "alternatenames", "lat", "lon", "fclass", "fcode",
                 "country", "cc2", "admin1", "admin2", "admin3", "admin4", "population", "elevation",
                 "dem", "timezone", "modified"]


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(a))


def load_cities(path: str | Path, countries: set[str] | None = None) -> pd.DataFrame:
    """GeoNames cities15000 (CC BY 4.0): populated places with population >= 15,000."""
    path = Path(path)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            fh = zf.open("cities15000.txt")
            df = pd.read_csv(fh, sep="\t", header=None, names=GEONAMES_COLS, dtype=str,
                             keep_default_na=False, quoting=3)
    else:
        df = pd.read_csv(path, sep="\t", header=None, names=GEONAMES_COLS, dtype=str,
                         keep_default_na=False, quoting=3)
    df = df[["geonameid", "name", "lat", "lon", "country", "admin1", "population", "fcode"]].copy()
    df[["lat", "lon"]] = df[["lat", "lon"]].astype(float)
    df["population"] = pd.to_numeric(df["population"], errors="coerce").fillna(0).astype("int64")
    # Drop sub-city sections (PPLX) so districts do not compete with their city.
    df = df[df["fcode"] != "PPLX"]
    if countries:
        df = df[df["country"].isin(countries)]
    return df.reset_index(drop=True)


def short_name(stop_name: str) -> str:
    for sep in (" (", ",", " - "):
        if sep in stop_name:
            stop_name = stop_name.split(sep)[0]
    return stop_name.strip()


def assign_places(stops: pd.DataFrame, cities: pd.DataFrame,
                  radius_km: float = CITY_RADIUS_KM) -> pd.DataFrame:
    """Map every stop to a place: the largest GeoNames city within radius, else the stop itself.

    Largest (not nearest) so that e.g. an airport stop 10 km out belongs to the city it serves.
    """
    s = stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]].copy()
    s["country"] = stops.get("stop_timezone", pd.Series("", index=stops.index)).map(TZ_TO_COUNTRY).fillna("")
    s["place_id"], s["place"], s["place_pop"], s["place_lat"], s["place_lon"] = "", "", 0, np.nan, np.nan

    clat, clon, cpop = cities["lat"].to_numpy(), cities["lon"].to_numpy(), cities["population"].to_numpy()
    ccountry = cities["country"].to_numpy()
    for i, row in s.iterrows():
        if np.isnan(row.stop_lat):
            continue
        d = haversine_km(row.stop_lat, row.stop_lon, clat, clon)
        same_country = (ccountry == row.country) if row.country else np.ones(len(ccountry), bool)
        near = np.where((d <= radius_km) & same_country)[0]  # never join a city across a border
        if len(near):
            j = near[np.argmax(cpop[near])]
            c = cities.iloc[j]
            s.loc[i, ["place_id", "place", "place_pop", "place_lat", "place_lon"]] = (
                f"gn:{c.geonameid}", c["name"], int(c.population), c.lat, c.lon)
            if not s.at[i, "country"]:
                s.at[i, "country"] = c.country
        else:
            s.loc[i, ["place", "place_lat", "place_lon"]] = (short_name(row.stop_name), row.stop_lat, row.stop_lon)
    _group_small_towns(s)
    s["place_pop"] = s["place_pop"].astype("int64")
    return s


def _group_small_towns(s: pd.DataFrame, merge_km: float = TOWN_MERGE_KM) -> None:
    """Stops outside any GeoNames city become a town place keyed by country and town name.

    Same-named stops within merge_km share one place, so a stop that is moved or re-keyed
    (e.g. a new stop ID 400 m away) stays the same place across feed versions. The key does not
    depend on stop IDs, which keeps it stable between snapshots.
    """
    towns: dict[str, list[tuple[float, float, str]]] = {}
    for i in s.index[s["place_id"] == ""]:
        if np.isnan(s.at[i, "stop_lat"]):
            continue
        base = f"town:{s.at[i, 'country']}:{s.at[i, 'place'].lower()}"
        lat, lon = s.at[i, "stop_lat"], s.at[i, "stop_lon"]
        pid = None
        for clat, clon, cid in towns.get(base, []):
            if haversine_km(lat, lon, clat, clon) <= merge_km:
                pid = cid
                s.loc[i, ["place_lat", "place_lon"]] = (clat, clon)
                break
        if pid is None:
            n = len(towns.get(base, []))
            pid = base if n == 0 else f"{base}#{n + 1}"
            towns.setdefault(base, []).append((lat, lon, pid))
        s.at[i, "place_id"] = pid
