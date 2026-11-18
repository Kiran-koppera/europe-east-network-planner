from openpyxl import load_workbook

from planner.quality import speed_exceptions
from planner.tracker import STATUSES, write_tracker

META = {"feed_start_date": "20260101", "feed_end_date": "20261231", "snapshot_date": "2026-01-19"}


def test_speed_exceptions_list_the_flagged_segment(feed):
    ex = speed_exceptions(feed)
    assert len(ex) == 1
    r = ex.iloc[0]
    assert (r.trip_id, r.from_stop_id, r.to_stop_id) == ("T3", "KRK", "PRG")
    assert (r.scheduled_departure, r.scheduled_arrival) == ("09:00:00", "09:30:00")


def test_tracker_workbook_structure(feed, tmp_path):
    path = tmp_path / "tracker.xlsx"
    stats = write_tracker(path, speed_exceptions(feed), feed["stops"], META)
    assert stats == {"issues": 1, "segments": 1, "both_direction_pairs": 0}
    wb = load_workbook(path)
    assert wb.sheetnames == ["Read me", "Issues", "Summary", "Settings", "Stops", "Segments"]
    iss, seg = wb["Issues"], wb["Segments"]
    assert iss["A2"].value == "DQ-SPD-001" and iss["K2"].value == "Open"
    assert "INDEX(Stops!" in seg["G2"].value and "MATCH(E2" in seg["G2"].value       # lookup
    assert seg["S2"].value.startswith("=IF(AND(P2>3,Q2>R2)")                          # exception flag
    lists = {str(dv.sqref): dv.formula1 for dv in iss.data_validations.dataValidation}
    assert lists["K2"].startswith("=Settings!$G$2") and lists["J2"].startswith("=Settings!$E$2")  # dropdowns
    assert [wb["Settings"].cell(row=r, column=7).value for r in range(2, 2 + len(STATUSES))] == STATUSES


def test_tracker_formulas_evaluate(feed, tmp_path):
    formulas = __import__("pytest").importorskip("formulas")
    path = tmp_path / "tracker.xlsx"
    write_tracker(path, speed_exceptions(feed), feed["stops"], META)
    sol = formulas.ExcelModel().loads(str(path)).finish().calculate()
    val = lambda sheet, cell: next(v.value[0][0] for k, v in sol.items() if k.upper().endswith(f"{sheet}'!{cell}"))  # noqa: E731
    assert val("SEGMENTS", "G2") == "Krakow (Bus Station)"
    assert val("SEGMENTS", "O2") == 30
    assert val("SEGMENTS", "S2") == "Exception"
    assert val("ISSUES", "F2") == 1
    assert val("SUMMARY", "B4") == 1                                                  # one Open issue
