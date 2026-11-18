from datetime import date

import pandas as pd
import pytest

from planner.calendar import active_days, reference_week
from planner.gtfs import to_seconds
from planner.quality import run_checks, scorecard


def test_times_past_midnight_parse():
    assert to_seconds("25:10:00") == 25 * 3600 + 600
    assert pd.isna(to_seconds("bad"))


def test_feed_loads_and_reports_nothing_missing(feed):
    assert feed.missing == []
    assert len(feed["stop_times"]) == 11


def test_reference_week_is_first_full_week_after_a_settling_period(feed):
    assert reference_week(feed) == (date(2026, 1, 12), date(2026, 1, 18))


def test_calendar_exceptions_add_and_remove_days(feed):
    days = active_days(feed, date(2026, 1, 12), date(2026, 1, 18))
    assert days["DAILY"] == 6     # 7 days minus the removed Wednesday
    assert days["WEEKEND"] == 3   # Saturday, Sunday plus the added Wednesday


def test_quality_checks_flag_exactly_the_planted_issues(feed):
    checks = {c.id: c for c in run_checks(feed)}
    assert checks["orphan_stops"].failed == 1 and "Nowhere stop" in checks["orphan_stops"].examples
    assert checks["empty_routes"].failed == 1 and checks["empty_routes"].examples == ["R3"]
    assert checks["speed"].failed == 1  # Krakow -> Prague in 30 minutes
    assert "Krakow (Bus Station) -> Prague (Florenc)" in checks["speed"].examples[0]
    failing = {k for k, c in checks.items() if not c.passed}
    assert failing == {"orphan_stops", "empty_routes", "speed"}


def test_scorecard_totals_are_consistent(feed):
    sc = scorecard(run_checks(feed))
    assert sc["checks"] == len(sc["results"])
    assert sc["passed"] + sc["errors"] + sc["warnings"] == sc["checks"]
    assert sc["records_flagged"] == 3
    assert 0 < sc["pass_rate"] < 100


def test_quality_detects_backwards_times(feed):
    broken = feed.tables["stop_times"].copy()
    broken.loc[broken.index[1], "arr_s"] = 0
    f = type(feed)(tables={**feed.tables, "stop_times": broken})
    checks = {c.id: c for c in run_checks(f)}
    assert checks["time_order"].failed == 1


@pytest.mark.parametrize("missing", ["stops", "trips"])
def test_missing_required_file_is_an_error(feed, missing):
    tables = {k: v for k, v in feed.tables.items() if k != missing}
    f = type(feed)(tables=tables, missing=[missing])
    files = {c.id: c for c in run_checks(f)}["files"]
    assert files.failed == 1 and files.severity == "error"
