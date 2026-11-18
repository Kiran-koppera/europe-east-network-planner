"""Data-quality issue tracker (Excel) for the implausible-speed check.

Built so a planner can work the issues, not just read them:

* Segments: one row per flagged segment. Stop names and coordinates come from the Stops sheet by
  INDEX/MATCH lookup; minutes, distance (haversine), speed and the exception flag are formulas,
  so correcting a coordinate in Stops re-evaluates the flag immediately.
* Issues: one row per stop pair, with trip counts and max speed by formula, a suspected cause,
  an owner and a status chosen from dropdowns. Everything starts Open until someone verifies it.
* Summary: open issues and affected trips by status and owner (COUNTIFS / SUMIFS). This stands in
  for a PivotTable, which openpyxl cannot create; the Issues table is ready for Insert > PivotTable.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from .config import MAX_BUS_SPEED_KMH, MAX_TRAIN_SPEED_KMH

STATUSES = ["Open", "In review", "Fixed in source", "Not an issue"]
OWNERS = ["Network data quality", "Network planning", "Partner operator", "Stop & station management"]
HEAD = PatternFill("solid", fgColor="1F4F7A")
WHITE = Font(color="FFFFFF", bold=True)
INPUT = PatternFill("solid", fgColor="FFF4D6")   # cells a planner fills in
THIN = Border(bottom=Side(style="thin", color="E2D9C8"))


def _excel_time(hhmmss: str) -> float:
    h, m, s = map(int, hhmmss.split(":"))
    return (h * 3600 + m * 60 + s) / 86400  # may exceed 1 for trips past midnight; shown as [h]:mm


def _header(ws, cols: list[str], widths: list[int]) -> None:
    for i, (c, w) in enumerate(zip(cols, widths), 1):
        cell = ws.cell(row=1, column=i, value=c)
        cell.fill, cell.font = HEAD, WHITE
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"


def suspected_cause(n_trips: int, both_directions: bool) -> str:
    if both_directions:
        return (f"Flagged in both directions on {n_trips} trips: likely a misplaced coordinate at one of the two "
                "stops (to verify on a map or with the operator)")
    return f"Running time too short for the distance on {n_trips} trips: check scheduled times or stop coordinates"


def write_tracker(path: Path, exceptions: pd.DataFrame, stops: pd.DataFrame, feed_meta: dict) -> dict:
    wb = Workbook()

    # --- Issues: one per directed stop pair
    pairs = (exceptions.groupby(["from_stop_id", "to_stop_id"]).size().rename("trips").reset_index()
             .sort_values("trips", ascending=False).reset_index(drop=True))
    keyset = set(zip(pairs["from_stop_id"], pairs["to_stop_id"]))
    pairs["both"] = [(t, f) in keyset for f, t in zip(pairs["from_stop_id"], pairs["to_stop_id"])]
    pairs["issue_id"] = [f"DQ-SPD-{i:03d}" for i in range(1, len(pairs) + 1)]
    issue_of = {(f, t): i for f, t, i in zip(pairs["from_stop_id"], pairs["to_stop_id"], pairs["issue_id"])}

    readme = wb.active
    readme.title = "Read me"
    lines = [
        ("Data-quality issue tracker: implausible segment speeds", True),
        (f"Feed: FlixBus GTFS Europe, valid {feed_meta.get('feed_start_date')}–{feed_meta.get('feed_end_date')}, "
         f"snapshot {feed_meta.get('snapshot_date')}.", False),
        ("", False),
        ("How to use", True),
        ("1. Issues: one row per stop pair. Set Owner and Status from the dropdowns; record who verified and when.", False),
        ("2. Segments: every flagged trip segment. Names, coordinates, minutes, distance, speed and flag are "
         "formulas.", False),
        ("3. Fixing a coordinate: correct it in Stops; the distance, speed and flag in Segments update immediately.", False),
        ("4. Summary: open issues and affected trips by status and owner. For a PivotTable, select the Issues table "
         "and use Insert > PivotTable.", False),
        ("", False),
        ("Rules", True),
        (f"Exception: straight-line segment longer than 3 km and faster than the mode limit "
         f"({MAX_BUS_SPEED_KMH:.0f} km/h coach, {MAX_TRAIN_SPEED_KMH:.0f} km/h train; see Settings).", False),
        ("A suspected cause stays a suspicion until verified; keep the issue Open until then.", False),
    ]
    for r, (text, bold) in enumerate(lines, 1):
        c = readme.cell(row=r, column=1, value=text)
        c.font = Font(bold=bold, size=13 if r == 1 else 11)
    readme.column_dimensions["A"].width = 120

    # --- Settings
    st = wb.create_sheet("Settings")
    _header(st, ["GTFS route_type", "Mode", "Speed limit (km/h)", "", "Owners", "", "Statuses"], [16, 12, 18, 3, 28, 3, 18])
    for r, (rt, mode, lim) in enumerate([(3, "Coach", MAX_BUS_SPEED_KMH), (2, "Train", MAX_TRAIN_SPEED_KMH)], 2):
        st.cell(row=r, column=1, value=rt)
        st.cell(row=r, column=2, value=mode)
        st.cell(row=r, column=3, value=lim)
    for r, o in enumerate(OWNERS, 2):
        st.cell(row=r, column=5, value=o)
    for r, s_ in enumerate(STATUSES, 2):
        st.cell(row=r, column=7, value=s_)
    owner_range = f"Settings!$E$2:$E${len(OWNERS) + 1}"
    status_range = f"Settings!$G$2:$G${len(STATUSES) + 1}"

    # --- Stops (source records)
    sp = wb.create_sheet("Stops")
    _header(sp, ["stop_id", "stop_name", "stop_lat", "stop_lon", "stop_timezone"], [40, 44, 12, 12, 18])
    srows = stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]].assign(
        stop_timezone=stops.get("stop_timezone", "")).sort_values("stop_id").itertuples(index=False)
    for r, row in enumerate(srows, 2):
        for c, v in enumerate(row, 1):
            sp.cell(row=r, column=c, value=v)
    n_stops = len(stops) + 1
    look = lambda col, key: f'INDEX(Stops!${col}$2:${col}${n_stops},MATCH({key},Stops!$A$2:$A${n_stops},0))'  # noqa: E731

    # --- Segments
    sg = wb.create_sheet("Segments")
    cols = ["Issue ID", "Trip ID", "Route ID", "Route type", "From stop ID", "To stop ID", "From stop", "To stop",
            "From lat", "From lon", "To lat", "To lon", "Sched. departure", "Sched. arrival", "Minutes",
            "Distance km", "Speed km/h", "Limit km/h", "Flag"]
    _header(sg, cols, [13, 30, 9, 9, 38, 38, 32, 32, 9, 9, 9, 9, 11, 11, 9, 11, 11, 10, 11])
    for r, e in enumerate(exceptions.itertuples(), 2):
        sg.cell(row=r, column=1, value=issue_of[(e.from_stop_id, e.to_stop_id)])
        sg.cell(row=r, column=2, value=e.trip_id)
        sg.cell(row=r, column=3, value=e.route_id)
        sg.cell(row=r, column=4, value=int(e.route_type))
        sg.cell(row=r, column=5, value=e.from_stop_id)
        sg.cell(row=r, column=6, value=e.to_stop_id)
        sg.cell(row=r, column=7, value=f"={look('B', f'E{r}')}")
        sg.cell(row=r, column=8, value=f"={look('B', f'F{r}')}")
        sg.cell(row=r, column=9, value=f"={look('C', f'E{r}')}")
        sg.cell(row=r, column=10, value=f"={look('D', f'E{r}')}")
        sg.cell(row=r, column=11, value=f"={look('C', f'F{r}')}")
        sg.cell(row=r, column=12, value=f"={look('D', f'F{r}')}")
        for c, v in ((13, e.scheduled_departure), (14, e.scheduled_arrival)):
            cell = sg.cell(row=r, column=c, value=_excel_time(v))
            cell.number_format = "[h]:mm"
        sg.cell(row=r, column=15, value=f"=ROUND((N{r}-M{r})*1440,0)")
        sg.cell(row=r, column=16, value=(f"=ROUND(6371.0088*2*ASIN(SQRT(SIN(RADIANS(K{r}-I{r})/2)^2+COS(RADIANS(I{r}))"
                                         f"*COS(RADIANS(K{r}))*SIN(RADIANS(L{r}-J{r})/2)^2)),1)"))
        sg.cell(row=r, column=17, value=f"=IF(O{r}>0,ROUND(P{r}/(O{r}/60),0),9999)")
        sg.cell(row=r, column=18, value=f"=INDEX(Settings!$C$2:$C$3,MATCH(D{r},Settings!$A$2:$A$3,0))")
        sg.cell(row=r, column=19, value=f'=IF(AND(P{r}>3,Q{r}>R{r}),"Exception","OK")')
    n_seg = len(exceptions) + 1
    sg.conditional_formatting.add(f"S2:S{n_seg}", CellIsRule(operator="equal", formula=['"Exception"'],
                                                             fill=PatternFill("solid", fgColor="FBD9C9")))

    # --- Issues
    iss = wb.create_sheet("Issues", 1)
    icols = ["Issue ID", "Check", "From stop ID", "To stop ID", "Stop pair", "Trips affected", "Exceptions now",
             "Max speed km/h", "Suspected cause", "Owner", "Status", "Verified by", "Verified on", "Next action", "Notes"]
    _header(iss, icols, [13, 16, 38, 38, 54, 10, 11, 11, 60, 24, 15, 14, 12, 52, 30])
    seg_a, seg_s, seg_q = f"Segments!$A$2:$A${n_seg}", f"Segments!$S$2:$S${n_seg}", f"Segments!$Q$2:$Q${n_seg}"
    for r, p in enumerate(pairs.itertuples(), 2):
        iss.cell(row=r, column=1, value=p.issue_id)
        iss.cell(row=r, column=2, value="Segment speed")
        iss.cell(row=r, column=3, value=p.from_stop_id)
        iss.cell(row=r, column=4, value=p.to_stop_id)
        iss.cell(row=r, column=5, value=f'={look("B", f"C{r}")}&" → "&{look("B", f"D{r}")}')
        iss.cell(row=r, column=6, value=f"=COUNTIF({seg_a},A{r})")
        iss.cell(row=r, column=7, value=f'=COUNTIFS({seg_a},A{r},{seg_s},"Exception")')
        iss.cell(row=r, column=8, value=f"=SUMPRODUCT(MAX(({seg_a}=A{r})*{seg_q}))")
        iss.cell(row=r, column=9, value=suspected_cause(int(p.trips), bool(p.both)))
        for c, v in ((10, "Network data quality"), (11, "Open")):
            cell = iss.cell(row=r, column=c, value=v)
            cell.fill = INPUT
        for c in (12, 13, 15):
            iss.cell(row=r, column=c).fill = INPUT
        iss.cell(row=r, column=13).number_format = "yyyy-mm-dd"
        iss.cell(row=r, column=14, value="Compare both stop coordinates with the real stop location; correct the "
                                         "master record or the scheduled times; re-run the check")
        iss.cell(row=r, column=9).alignment = iss.cell(row=r, column=14).alignment = Alignment(wrap_text=True,
                                                                                               vertical="top")
    n_iss = len(pairs) + 1
    dv_owner = DataValidation(type="list", formula1=f"={owner_range}", allow_blank=False)
    dv_status = DataValidation(type="list", formula1=f"={status_range}", allow_blank=False)
    dv_status.error, dv_status.errorTitle = "Pick a status from the list.", "Status"
    iss.add_data_validation(dv_owner)
    iss.add_data_validation(dv_status)
    dv_owner.add(f"J2:J{n_iss}")
    dv_status.add(f"K2:K{n_iss}")
    iss.conditional_formatting.add(f"A2:O{n_iss}", FormulaRule(formula=['$K2="Open"'],
                                                                fill=PatternFill("solid", fgColor="FFF8EC")))
    tab = Table(displayName="Issues", ref=f"A1:O{n_iss}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=False)
    iss.add_table(tab)

    # --- Summary
    sm = wb.create_sheet("Summary", 2)
    sm.column_dimensions["A"].width = 30
    for col in "BCD":
        sm.column_dimensions[col].width = 18
    sm["A1"] = "Issue summary"
    sm["A1"].font = Font(bold=True, size=14)
    sm["A3"], sm["B3"], sm["C3"] = "Status", "Issues", "Trips affected"
    rng_k, rng_f, rng_j = f"Issues!$K$2:$K${n_iss}", f"Issues!$F$2:$F${n_iss}", f"Issues!$J$2:$J${n_iss}"
    for r, s_ in enumerate(STATUSES, 4):
        sm.cell(row=r, column=1, value=s_)
        sm.cell(row=r, column=2, value=f'=COUNTIF({rng_k},A{r})')
        sm.cell(row=r, column=3, value=f'=SUMIFS({rng_f},{rng_k},A{r})')
    tr = 4 + len(STATUSES)
    sm.cell(row=tr, column=1, value="Total").font = Font(bold=True)
    sm.cell(row=tr, column=2, value=f"=SUM(B4:B{tr - 1})").font = Font(bold=True)
    sm.cell(row=tr, column=3, value=f"=SUM(C4:C{tr - 1})").font = Font(bold=True)
    o0 = tr + 2
    sm.cell(row=o0, column=1, value="Owner")
    sm.cell(row=o0, column=2, value="Open issues")
    sm.cell(row=o0, column=3, value="Open trips")
    for r, o in enumerate(OWNERS, o0 + 1):
        sm.cell(row=r, column=1, value=o)
        sm.cell(row=r, column=2, value=f'=COUNTIFS({rng_j},A{r},{rng_k},"Open")')
        sm.cell(row=r, column=3, value=f'=SUMIFS({rng_f},{rng_j},A{r},{rng_k},"Open")')
    for hr in (3, o0):
        for c in range(1, 4):
            cell = sm.cell(row=hr, column=c)
            cell.fill, cell.font = HEAD, WHITE
    sm.cell(row=o0 + len(OWNERS) + 2, column=1,
            value="Counts update when Owner or Status changes on the Issues sheet.").font = Font(italic=True, color="6A5B4B")

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return {"issues": int(len(pairs)), "segments": int(len(exceptions)),
            "both_direction_pairs": int(pairs["both"].sum())}
