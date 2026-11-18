# Method

## 1. Reference week

The feed covers six months, and every trip has its own calendar. All service figures use one
**reference week**: the first full Monday–Sunday week starting at least 7 days after the feed
start date (for the 15 Nov 2026 feed: 23–29 Nov 2026). A trip's weekly runs are the days its service
runs in that week, after applying `calendar_dates` additions (type 1) and removals (type 2).

## 2. Stops to cities

A stop belongs to the **largest** GeoNames city (population ≥ 15,000) within 12 km; otherwise it
stands alone as its own place. Largest rather than nearest, so that an airport or edge-of-town stop
counts for the city it serves. The country comes from the stop's IANA timezone.

## 3. City pairs

For every trip running in the reference week, every ordered pair of calls (earlier → later stop) is a
possible journey without changing vehicles. Calls in the same city are skipped, and if a trip calls
twice in one city the fastest leg is kept. Pairs are made undirected and aggregated:

- `weekly_departures`: trip runs per week, both directions
- `fastest_min`, `median_min`: in-vehicle time from the timetable

## 4. Demand gaps

Candidate pairs: at least one city in the 15 Europe East countries, both cities ≥ 100,000 people,
straight-line distance 150–1,200 km. City districts listed separately in GeoNames are merged into
the largest city within 15 km. Excluded: Turkey (separate Flix feed) and occupied or front-line
Ukrainian regions (`EXCLUDED_REGIONS` in `config.py`).

Demand index (gravity model, β = 2), scaled so the strongest pair scores 100:

    index = 100 × (P_a × P_b / d²) / max(P_a × P_b / d²)

Status, in order of severity:

| Status | Rule |
|---|---|
| No service: city not on network | at least one city has no stop within 12 km |
| No direct service | both on network, no direct trip, no common neighbour |
| Transfer only | no direct trip, but at least one city has direct trips to both |
| Low frequency | direct, fewer than 14 departures a week (both directions) |
| Served | 14 or more |

**Calibration.** On pairs served today, the Spearman rank correlation between the index and weekly
departures is reported (0.447 on the first snapshot). It tells a planner how much of today's network
the index explains. It is a sanity check, not a validation: today's network also reflects history,
partners, rail competition and constraints the index does not see.

## 5. Changelog

Each run stores a gzipped snapshot (all places, all direct pairs touching Europe East, weekly
departures) in `data/history/`. The next run compares against the latest earlier snapshot and lists
added and removed places and pairs, and frequency changes of at least 7 departures a week.
