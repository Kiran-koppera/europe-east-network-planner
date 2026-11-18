# Method

## 1. Reference week

The feed covers six months and every trip has its own calendar. Service figures use one **reference
week**: the first full Monday–Sunday week starting at least 7 days after the feed start date (for the
15 Nov 2026 feed: 23–29 Nov 2026). A trip's weekly runs are the days its service runs in that week,
after `calendar_dates` additions (type 1) and removals (type 2).

## 2. Stops to places

- A stop belongs to the **largest** GeoNames city (population ≥ 15,000) **in the same country** within
  12 km. Largest rather than nearest, so an airport stop counts for the city it serves; same country, so
  Giurgiu (RO) is never merged into Ruse (BG) across the Danube.
- Other stops become a **town**, keyed by country and town name; same-named stops within 5 km share it.
  The key does not depend on stop IDs, so a stop that is moved or re-keyed stays the same place between
  feed versions.
- The country comes from the stop's IANA timezone.

## 3. City pairs

For every trip running in the reference week, every ordered pair of calls is a journey without changing
vehicles. Calls in the same place are skipped; if a trip calls twice in one place, the fastest leg is
kept. Pairs are made undirected: `weekly_departures` (both directions), `fastest_min`, `median_min`.

## 4. Demand gaps

Candidates: at least one city in the 15 Europe East countries, both ≥ 100,000 people, 150–1,200 km apart.
GeoNames districts are merged into the largest city within 15 km. Excluded: Turkey (separate Flix feed)
and occupied or front-line Ukrainian regions (`EXCLUDED_REGIONS`); Kharkiv is not excluded because the
feed serves it.

    index = 100 × (P_a × P_b / d²) / max(P_a × P_b / d²)

| Status (all candidates) | Rule |
|---|---|
| No service: city not on network | at least one city has no stop within 12 km |
| No direct service | both on network, no direct trip, no city linked to both |
| Linked via hub (untimed) | no direct trip; some city has direct trips to both ends |
| Low frequency | direct, fewer than 14 departures a week (both directions) |
| Served | 14 or more |

**Calibration:** Spearman rank correlation between the index and weekly departures on served pairs
(0.446). A sanity check of how much of today's network the index explains, not a validation.

## 5. Timed transfers (top 50 opportunities)

"Linked via hub" says nothing about timing, so each such opportunity is checked against the timetable:

- Legs carry real dates from the calendar, so a trip only connects on days both legs run, and overnight
  times (past 24:00) land on the right day.
- A connection needs **15–180 minutes** at the hub. Itineraries start within the reference week.
- A transfer is **practical** if its end-to-end time is at most **2 × the direct coach time + 1 hour**
  (direct time = 1.25 × straight-line km at 70 km/h).

Result per opportunity: *Practical transfer*, *Practical transfer (one direction)* or *No practical
transfer*, with the fastest itinerary and hub in each direction. Example: Sofia – Belgrade is linked via
four cities, but the only working connection goes via Istanbul in 23 h 25 min.

## 6. Changelog

Each run stores a gzipped snapshot with weekly departures for **8 consecutive calendar weeks**, per place,
per Europe East stop and per direct city pair touching Europe East. The diff compares the current
feed's reference week with **the same calendar week** in the previous snapshot. Comparing each feed's own
first week would turn ordinary week-to-week differences into changes; on the 8 → 15 Nov feeds that
would have added 17 changes that did not happen ([case](changelog-case.md)). Events: stops and places
added or removed, direct pairs added or removed, and frequency changes of at least 7 departures a week.

## 7. Worked case

See [line-dossier.md](line-dossier.md) and the [Bucharest – Plovdiv case](worked-case-bucharest-plovdiv.md).
