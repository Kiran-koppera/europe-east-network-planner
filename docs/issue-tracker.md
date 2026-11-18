# Data-quality issue tracker

[Download the tracker (.xlsx)](https://kiran-koppera.github.io/europe-east-network-planner/data/data-quality-issue-tracker.xlsx)
· generated every week by `python -m planner run`.

The speed check flags 68 trip segments on 12 stop pairs in the 15 Nov 2026 feed. The tracker turns that
finding into work a planning team can assign, follow and close.

| Sheet | What it holds |
|---|---|
| **Issues** | One row per stop pair (DQ-SPD-001 … 012): trips affected and exceptions now (COUNTIF/COUNTIFS), max speed (SUMPRODUCT), suspected cause, **Owner** and **Status** dropdowns, verified by / on, next action. Formatted as an Excel table, ready for Insert ▸ PivotTable. |
| **Summary** | Issues and affected trips by status, open issues and trips by owner (COUNTIFS / SUMIFS). Updates when a status changes. |
| **Segments** | One row per flagged segment: trip, route and stop IDs, scheduled departure and arrival. Stop names and coordinates come from **Stops** by INDEX/MATCH; minutes, haversine distance, speed and the **Exception** flag are formulas. |
| **Stops** | The source records (all 2,085 stops). Correct a coordinate here and the segment's distance, speed and flag re-evaluate. |
| **Settings** | Speed limits by GTFS route type, owner list, status list. |

All 68 flags were checked by evaluating the workbook's formulas in Python (`formulas` package): every
segment evaluates to *Exception*, with speeds of 121–270 km/h, matching the pipeline.

**Example: DQ-SPD-001, Rokovci → Sopot R.** 9 trips (Zagreb – Vukovar), 7.3 km in 3 minutes = 146 km/h.
The reverse direction (DQ-SPD-002) is flagged on the same 9 trips, and the next segment to Vinkovci runs
at 44 km/h. A misplaced *Sopot R* coordinate is the likely cause, but it stays **Open** until someone
compares the stop with its real location. Two stop pairs (Rokovci ↔ Sopot R, Ston ↔ Doli) are flagged in
both directions, 4 of the 12 issue rows.

openpyxl cannot create PivotTables, so the Summary sheet uses formulas instead; the Issues table is
ready for a PivotTable in one click.
