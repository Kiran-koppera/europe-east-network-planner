from datetime import timedelta

import pandas as pd
import pytest

from planner import changelog, transfers
from planner.demand import calibrate, candidate_pairs, classify, eligible_cities, opportunities, unserved_cities
from planner.dossier import build_case, legal_basis, timetable, vehicle_blocks, write_dossier
from planner.geo import assign_places
from planner.network import weekly_series


def pair(pairs, x, y):
    m = pairs[((pairs["a_name"] == x) & (pairs["b_name"] == y)) | ((pairs["a_name"] == y) & (pairs["b_name"] == x))]
    assert len(m) == 1, (x, y)
    return m.iloc[0]


def pid(model, name):
    return model["places"].set_index("place")["place_id"][name]


# ------------------------------------------------------------------ places
def test_stops_are_grouped_into_the_largest_nearby_city(model):
    sp = model["stop_places"].set_index("stop_id")
    assert sp.loc["WAW1", "place"] == sp.loc["WAW2", "place"] == "Warsaw"   # not the Wola district
    assert sp.loc["ORPH", "place_id"] == "town:PL:nowhere stop"             # no city within 12 km
    assert sp.loc["VIE", "country"] == "AT"


def test_stops_never_join_a_city_across_a_border(cities):
    # A Czech stop 2 km from Warsaw's coordinates must not become part of Warsaw (PL).
    stops = pd.DataFrame({"stop_id": ["X"], "stop_name": ["Border stop"], "stop_lat": [52.24], "stop_lon": [21.02],
                          "stop_timezone": ["Europe/Prague"]})
    sp = assign_places(stops, cities)
    assert sp.loc[0, "place_id"].startswith("town:CZ:")


def test_small_town_id_is_stable_when_a_stop_is_added_nearby(cities):
    one = pd.DataFrame({"stop_id": ["b"], "stop_name": ["Pyriatyn, gas station"], "stop_lat": [50.2189],
                        "stop_lon": [32.5195], "stop_timezone": ["Europe/Kyiv"]})
    two = pd.concat([pd.DataFrame({"stop_id": ["a"], "stop_name": ["Pyriatyn, near bus station"],
                                   "stop_lat": [50.2214], "stop_lon": [32.5161], "stop_timezone": ["Europe/Kyiv"]}), one])
    p1 = assign_places(one, cities).set_index("stop_id")["place_id"]
    p2 = assign_places(two.reset_index(drop=True), cities).set_index("stop_id")["place_id"]
    assert p1["b"] == p2["b"] == p2["a"] == "town:UA:pyriatyn"


# ------------------------------------------------------------------ network
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


def test_weekly_series_covers_consecutive_weeks(feed, model):
    weeks, places, pairs, stops = weekly_series(feed, model["stop_places"], model["week"][0], n_weeks=3)
    assert weeks == ["2026-01-12", "2026-01-19", "2026-01-26"]
    key = "|".join(sorted([pid(model, "Warsaw"), pid(model, "Krakow")]))
    assert list(pairs.loc[key]) == [9, 9, 9]       # Jan 14 exceptions only touch the first week
    assert stops.loc["KRK"].tolist()[1] == 7 + 2 + 7 + 7   # T1, T2 (weekend), T3, T4 in a normal week


# ------------------------------------------------------------------ demand
def test_eligible_cities_exclude_war_zones_and_merge_districts(cities):
    names = set(eligible_cities(cities)["name"])
    assert "Donetsk" not in names       # excluded region
    assert "Wola" not in names          # district merged into Warsaw
    assert {"Warsaw", "Krakow", "Prague", "Budapest", "Vienna"} <= names


def test_classification_of_service_levels(cities, model):
    cl = classify(candidate_pairs(cities), model["pairs"], model["places"])
    status = {tuple(sorted((r.a_name, r.b_name))): r.status for r in cl.itertuples()}
    assert status[("Krakow", "Warsaw")] == "Low frequency"
    assert status[("Prague", "Warsaw")] == "Linked via hub (untimed)"
    assert status[("Budapest", "Warsaw")] == "No service: city not on network"
    assert cl["demand_index"].max() == 100
    assert calibrate(cl)["served_pairs"] == 4
    opp = opportunities(cl)
    assert (opp["status"] != "Served").all() and list(opp["rank"]) == sorted(opp["rank"])
    assert list(unserved_cities(cities, model["places"])["name"]) == ["Budapest"]


# ------------------------------------------------------------------ transfers
def test_timed_connection_respects_days_and_change_window(feed, model):
    w0, w1 = model["week"]
    legs = transfers.timed_legs(feed, model["stop_places"], w0, w1 + timedelta(days=1),
                                {pid(model, "Warsaw"), pid(model, "Prague")})
    conn = transfers.connections(legs, pid(model, "Warsaw"), pid(model, "Prague"), last_start=w1)
    s = transfers.summarize(conn)
    # T1 (Warsaw 08:25) arrives Krakow 11:00, T4 leaves 11:30: 6 days (Wed 14 Jan removed).
    assert s["weekly_itineraries"] == 6 and s["best_total_min"] == 485
    assert set(conn["wait_min"]) == {30}
    # The overnight weekend trip reaches Krakow at 01:00: 10.5 h wait, outside the window.
    assert not conn["trip_id_1"].eq("T2").any()
    # A 45-minute minimum change time breaks every connection.
    assert transfers.connections(legs, pid(model, "Warsaw"), pid(model, "Prague"), min_transfer=45).empty


def test_refine_replaces_untimed_status(feed, cities, model):
    cl = classify(candidate_pairs(cities), model["pairs"], model["places"])
    opp = transfers.refine(opportunities(cl), feed, model["stop_places"], model["pairs"], model["places"], model["week"])
    row = opp[(opp["a_name"].isin(["Warsaw", "Prague"])) & (opp["b_name"].isin(["Warsaw", "Prague"]))].iloc[0]
    assert row["status"].startswith("Practical transfer")
    assert "Linked via hub (untimed)" not in set(opp["status"])


# ------------------------------------------------------------------ changelog
def _snap(date_, weeks, pairs, stops=None):
    return {"version": 2, "meta": {"snapshot_date": date_}, "weeks": weeks,
            "places": {"p1": ["A", "PL", [5] * len(weeks)], "p2": ["B", "PL", [5] * len(weeks)]},
            "pairs": pairs, "stops": stops or {}}


def test_changelog_compares_the_same_calendar_week():
    prev = _snap("2026-11-09", ["2026-11-16", "2026-11-23"], {"p1|p2": [50, 20]},
                 {"s1": ["Old stop", "A", [5, 5]]})
    curr = _snap("2026-11-16", ["2026-11-23", "2026-11-30"], {"p1|p2": [20, 20]},
                 {"s1": ["Old stop", "A", [5, 5]], "s2": ["New stop", "A", [3, 3]]})
    d = changelog.diff(prev, curr)
    assert d["week"] == "2026-11-23" and d["comparable"]
    # Same week: 20 -> 20 is no change, although the feeds' own first weeks differ (50 vs 20).
    assert d["summary"]["frequency_down"] == 0
    assert d["summary"]["stops_added"] == 1 and d["events"][0]["item"] == "New stop (A)"


def test_changelog_reports_when_no_common_week():
    prev = _snap("2026-10-01", ["2026-10-05"], {"p1|p2": [10]})
    curr = _snap("2026-11-16", ["2026-11-23"], {"p1|p2": [10]})
    d = changelog.diff(prev, curr)
    assert d["comparable"] is False and "does not cover" in d["note"]
    assert changelog.diff(None, curr)["baseline"] is True


def test_previous_snapshot_skips_old_format(tmp_path):
    import gzip
    import json
    (tmp_path / "2026-11-01.json.gz").write_bytes(gzip.compress(json.dumps({"meta": {}}).encode()))
    assert changelog.previous_snapshot(tmp_path, "2026-11-18") is None
    changelog.save_snapshot(_snap("2026-11-09", ["2026-11-16"], {}), tmp_path)
    assert changelog.previous_snapshot(tmp_path, "2026-11-18")["meta"]["snapshot_date"] == "2026-11-09"


# ------------------------------------------------------------------ dossier
def test_legal_basis_depends_on_countries():
    assert "1073/2009" in legal_basis(["RO", "BG"])[0]
    assert "PBefG" in legal_basis(["DE"])[0]
    assert "bilateral" in legal_basis(["RS", "BG"])[0]


def test_timetable_inserts_statutory_break():
    tt = timetable(["A", "B"], [300], ["08:00"])                  # 5 h driving
    assert list(tt["Dep. 08:00"]) == ["08:00", "13:45"]          # + 45 min break


def test_vehicle_blocks_chain_trips_with_layover():
    out = timetable(["A", "B"], [120], ["07:00", "12:00"])
    ret = timetable(["B", "A"], [120], ["07:00", "12:00"])
    blocks = vehicle_blocks(out, ret, "A", "B")
    assert len(blocks) == 2                                       # 07:00 out, 12:00 back on each coach


@pytest.fixture()
def wp_case(feed, model):
    places = model["places"]
    opp = {"a": pid(model, "Warsaw"), "b": pid(model, "Prague"), "status": "Practical transfer",
           "weekly_departures": 0, "transfer_hubs": 1, "demand_index": 50.0, "rank": 1, "km": 517.0}
    ctx = dict(feed=feed, stop_places=model["stop_places"], week=model["week"], legs=model["legs"],
               pairs=model["pairs"], stop_weekly=model["stop_weekly"])
    return opp, places, ctx


def test_worked_case_numbers(wp_case):
    opp, places, ctx = wp_case
    case = build_case(opp, places, **ctx)
    assert case["route"]["stop"].iloc[0] == "Warsaw (West)"        # busiest Warsaw stop
    assert case["hubs"] == ["Krakow"]
    out = case["options"].set_index("Direction").loc["Warsaw → Prague"]
    assert out["Itineraries / week"] == 6 and out["Practical"] == "yes"
    assert case["best"]["outbound"]["total_min"] == 485
    assert "1073/2009" in case["legal"][0]


def test_dossier_is_written(wp_case, tmp_path):
    opp, places, ctx = wp_case
    path, case = write_dossier(opp, places, {"feed_start_date": "20260101", "feed_end_date": "20261231"}, tmp_path, **ctx)
    assert path.exists() and path.stat().st_size > 10_000
    assert (tmp_path / (path.stem + "-map.png")).exists()
