from pathlib import Path

import pytest

from planner.calendar import reference_week
from planner.config import TZ_TO_COUNTRY
from planner.geo import assign_places, load_cities
from planner.gtfs import load_feed
from planner.network import city_pairs, od_legs, place_table, trip_weekly_runs

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def feed():
    return load_feed(FIX / "mini_feed")


@pytest.fixture(scope="session")
def cities():
    return load_cities(FIX / "cities_mini.txt", set(TZ_TO_COUNTRY.values()) | {"UA"})


@pytest.fixture(scope="session")
def model(feed, cities):
    sp = assign_places(feed["stops"], cities)
    runs = trip_weekly_runs(feed, *reference_week(feed))
    legs = od_legs(feed, sp, runs)
    places = place_table(sp, legs)
    return {"stop_places": sp, "runs": runs, "legs": legs, "places": places, "pairs": city_pairs(legs, places)}
