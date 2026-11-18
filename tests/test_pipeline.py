import json
from pathlib import Path

from openpyxl import load_workbook

from planner.pipeline import Paths, run

FIX = Path(__file__).parent / "fixtures"


def test_pipeline_end_to_end(tmp_path):
    res = run(Paths(FIX / "mini_feed", FIX / "cities_mini.txt", tmp_path / "out", tmp_path / "hist"), "2026-01-19")
    m = res["metrics"]
    assert m["feed"]["stop_times"] == 9
    assert m["reference_week"]["city_pairs"] == 4
    assert m["quality"]["checks"] == 15
    site = tmp_path / "out" / "site" / "data"
    for f in ["meta.json", "network.json", "opportunities.json", "quality.json", "changelog.json",
              "countries.json", "europe-east-network-report.xlsx"]:
        assert (site / f).exists(), f
    assert json.loads((site / "changelog.json").read_text())["baseline"] is True
    wb = load_workbook(tmp_path / "out" / "reports" / "europe-east-network-report.xlsx")
    assert {"Summary", "Data quality", "Country KPIs", "Opportunities"} <= set(wb.sheetnames)

    # A second weekly run compares against the first snapshot.
    res2 = run(Paths(FIX / "mini_feed", FIX / "cities_mini.txt", tmp_path / "out", tmp_path / "hist"), "2026-01-26")
    assert res2["metrics"]["changelog"]["baseline"] is False
