import json

import pandas as pd

from planner import changelog
from planner.demand import calibrate, candidate_pairs, classify, eligible_cities, opportunities, unserved_cities
from planner.dossier import legal_basis, timetable, write_dossier


def pair(pairs, x, y):
    m = pairs[((pairs["a_name"] == x) & (pairs["b_name"] == y)) | ((pairs["a_name"] == y) & (pairs["b_name"] == x))]
    assert len(m) == 1, (x, y)
    return m.iloc[0]


def test_stops_are_grouped_into_the_largest_nearby_city(model):
    sp = model["stop_places"].set_index("stop_id")
    assert sp.loc["WAW1", "place"] == sp.loc["WAW2", "place"] == "Warsaw"   # not the Wola district
    assert sp.loc["ORPH", "place_id"].startswith("stop:")                  # no city within 12 km
    assert sp.loc["VIE", "country"] == "AT"


def test_weekly_departures_and_fastest_time(model):
    p = pair(model["pairs"], "Warsaw", "Krakow")
    assert p["weekly_departures"] == 9          # 6 daily runs + 3 weekend runs
    assert p["fastest_min"] == 155              # boarding at the second Warsaw stop
    assert not p["cross_border"]
    assert pair(model["pairs"], "Krakow", "Vienna")["cross_border"]


def test_same_city_hops_are_not_city_pairs(model):
    pairs = model["pairs"]
    assert not (pairs["a"] == pairs["b"]).any()
    assert set(pairs["a_name"]) | set(pairs["b_name"]) == {"Warsaw", "Krakow", "Vienna", "Prague"}


def test_eligible_cities_exclude_war_zones_and_merge_districts(cities):
    names = set(eligible_cities(cities)["name"])
    assert "Donetsk" not in names       # excluded region
    assert "Wola" not in names          # district merged into Warsaw
    assert {"Warsaw", "Krakow", "Prague", "Budapest", "Vienna"} <= names


def test_classification_of_service_levels(cities, model):
    cl = classify(candidate_pairs(cities), model["pairs"], model["places"])
    status = {tuple(sorted((r.a_name, r.b_name))): r.status for r in cl.itertuples()}
    assert status[("Krakow", "Warsaw")] == "Low frequency"
    assert status[("Prague", "Warsaw")] == "Transfer only"          # change in Krakow
    assert status[("Budapest", "Warsaw")] == "No service: city not on network"
    assert cl["demand_index"].max() == 100
    assert calibrate(cl)["served_pairs"] == 4
    opp = opportunities(cl)
    assert (opp["status"] != "Served").all() and list(opp["rank"]) == sorted(opp["rank"])
    assert list(unserved_cities(cities, model["places"])["name"]) == ["Budapest"]


def test_changelog_detects_added_removed_and_frequency_changes(model):
    meta = {"snapshot_date": "2026-01-19"}
    curr = changelog.snapshot(meta, model["places"], model["pairs"])
    prev = json.loads(json.dumps(curr))
    prev["meta"] = {"snapshot_date": "2026-01-12"}
    key = next(iter(prev["pairs"]))
    prev["pairs"][key] += 20                                # frequency went down since last week
    prev["pairs"]["x|y"] = 7                                # pair dropped
    del prev["places"][next(iter(prev["places"]))]          # place is new this week
    d = changelog.diff(prev, curr)
    assert d["summary"] == {"places_added": 1, "places_removed": 0, "pairs_added": 0, "pairs_removed": 1,
                            "frequency_up": 0, "frequency_down": 1}
    assert changelog.diff(None, curr)["baseline"] is True


def test_legal_basis_depends_on_countries():
    assert "1073/2009" in legal_basis(["RO", "BG"])[0]
    assert "PBefG" in legal_basis(["DE"])[0]
    assert "bilateral" in legal_basis(["RS", "BG"])[0]


def test_timetable_inserts_statutory_break():
    route = pd.DataFrame({"place": ["A", "B"], "km_from_origin": [0, 350]})   # 5 h driving
    tt = timetable(route, ["08:00"])
    assert list(tt["Dep. 08:00"]) == ["08:00", "13:45"]                   # 5 h + 45 min break


def test_dossier_is_written(model, tmp_path):
    places = model["places"]
    w = places.set_index("place")["place_id"]
    opp = {"a": w["Warsaw"], "b": w["Vienna"], "status": "Low frequency", "weekly_departures": 9,
           "transfer_hubs": 1, "demand_index": 50.0, "rank": 1, "km": 556.0}
    path = write_dossier(opp, places, {"feed_start_date": "20260101", "feed_end_date": "20261231"}, tmp_path)
    assert path.exists() and path.stat().st_size > 10_000
    assert (tmp_path / (path.stem + "-map.png")).exists()
