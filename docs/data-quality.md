# Data-quality checks

Every run executes 15 checks. Each reports records checked, records failing, severity and up to five
examples, so the record can be found and fixed in the source system. The weekly workflow **fails**
when any error-level check fails.

| # | Check | Severity | Rule |
|---|---|---|---|
| 1 | Required files present | error | agency, stops, routes, trips, stop_times and a calendar file |
| 2 | Required columns present | error | key columns of each required file |
| 3 | Stops have valid coordinates | error | lat/lon present, in range, not (0, 0) |
| 4 | Stop IDs are unique | error | no duplicate `stop_id` |
| 5 | Stop times reference existing stops | error | every `stop_times.stop_id` exists |
| 6 | Stop times reference existing trips | error | every `stop_times.trip_id` exists |
| 7 | Trips reference routes and calendars | error | `route_id` and `service_id` exist |
| 8 | Every stop is served | warning | no stop without a trip |
| 9 | Every route has a trip | warning | no empty route |
| 10 | Trips have at least two stops | error | |
| 11 | Times never go backwards | error | arrival ≥ previous departure; departure ≥ arrival |
| 12 | Segment speeds are plausible | warning | > 3 km hops: ≤ 120 km/h by bus, ≤ 250 km/h by train |
| 13 | Calendar ranges are valid | error | end date not before start date |
| 14 | Services run on at least one day | warning | weekday flags or an added date |
| 15 | Feed validity is consistent | error | feed end date not before start date |

If checks 1 or 2 fail, the content checks are skipped: they would only produce noise.

## First snapshot (18 Nov 2026)

984,520 records checked, 0 errors, 1 warning: 68 segments faster than 120 km/h. The leading case is
Rokovci → Sopot R on the Zagreb – Vukovar trips (7.3 km in 3 minutes, then 2.2 km in 3 minutes to
Vinkovci). A misplaced *Sopot R* coordinate is the likely cause.
