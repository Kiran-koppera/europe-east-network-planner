# A real network change between two feed versions

**Feeds compared:** FlixBus GTFS Europe as published on 8 Nov 2026 (valid 8 Nov 2026 – 8 May 2027,
archived by [transport.data.gouv.fr](https://transport.data.gouv.fr/datasets/reseau-europeen-flixbus-et-flixtrain))
and on 15 Nov 2026 (valid 15 Nov 2026 – 15 May 2027).
**Week compared:** 23–29 Nov 2026, which both feeds cover.

## Why the comparison week matters

Each feed's own reference week starts 7 days after its start date, so the two feeds' first weeks
are 16–22 Nov and 23–29 Nov. Comparing those would mix a network change with an ordinary
week-to-week difference. Measured on these two feeds:

| Method | Pairs added | Pairs removed | Frequency up | Frequency down |
|---|---|---|---|---|
| Each feed's own first week (old logic) | 8 | **21** | **9** | 3 |
| Same calendar week, 23–29 Nov (current logic) | 8 | 9 | 4 | 3 |

The old logic would have reported 12 pair removals and 5 frequency increases that did not happen.
Snapshots now store 8 calendar weeks, and the diff always uses a week both feeds cover.

## The change: line 1304 now serves Łódź instead of Sieradz

Line **1304 Warsaw – Dresden – Brussels** runs 10 times a week in each feed. On the 8 Nov feed it
calls at **Sieradz** (13:07). On the 15 Nov feed it calls at **Łódź** (12:10) instead, and leaves
Warsaw 20 minutes earlier (10:35 instead of 10:55). From Wrocław onwards the times are unchanged
(Dresden +10 min, Brussels arrival unchanged at 08:30 the next morning).

| Effect (week of 23 Nov) | Before | After |
|---|---|---|
| Sieradz – Brussels, Dortmund, Duisburg, Essen, Halle, Leipzig, Maastricht, Mönchengladbach, Bolesławiec | 10 / week each | removed |
| Łódź – Brussels, Dortmund, Essen, Halle, Leipzig, Maastricht, Mönchengladbach, Bolesławiec | – | 10 / week each |
| Łódź – Warsaw | 180 | 190 |
| Sieradz – Warsaw | 34 | 24 |
| Sieradz – Wrocław | 34 | 24 |
| Sieradz – Dresden | 24 | 14 |

**What it means:** Łódź (population 639,890, GeoNames) gains direct links to the Ruhr, Saxony, Limburg and Brussels.
Sieradz (44,436) loses its direct links to Bolesławiec and everything west of Dresden, and keeps 24 weekly departures
each to Warsaw and Wrocław.

**Follow-up a planner would open:**

1. Customers booked from or to Sieradz on line 1304 after the change date: rebooking or refund
   offers (Customer service).
2. Stop information at Sieradz bus station: remove line 1304 departures (Stop & station management).
3. Łódź bus station: slot for the 12:10 call, platform and stop page (Stop & station management).
4. Fares and inventory for the new Łódź city pairs (Pricing).
5. Check the Sieradz – Germany demand that is now lost: is a connection via Wrocław practical,
   or should another line pick up Sieradz? (Network planning)

## A second change the changelog catches: a stop move in Pyriatyn

Half of Pyriatyn's 14 weekly departures (Ukraine, Kyiv – Poltava corridor) moved from the
*"AMIC Energy" gas station* stop to a new stop *Near BS "Pyriatyn"* 370 m away. The changelog lists it
as **stop added**, not as a new place or new connections: stops outside a GeoNames city are grouped
into a town by name within 5 km, with an ID that does not depend on stop IDs. Follow-up: confirm
whether the remaining departures should move too, and update the stop page.
