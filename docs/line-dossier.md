# Worked case and line-authorization dossier

`python -m planner run` writes a worked case (`.docx`) and an overview map (`.png`) for the
highest-ranked opportunity between two cities already on the network, preferring an intra-EU
cross-border pair and skipping low-frequency pairs (those already have a line).

## Contents

1. **Decision summary**: line, stops, road km, end-to-end time, today's best options, fleet; a
   lower-cost option (retiming an existing trip) is tested first when a hub misses by less than an hour.
2. **What passengers can do today**: every hub, both directions, every day of the week: itineraries,
   fastest time, practical or not, and the closest miss where nothing connects.
3. **Route, stops and running times**: up to three intermediate network cities (≥ 50,000 people) within
   25 km of the corridor; of two cities closer than 15 km, the one giving more observed segments is kept.
   Each city gets its **busiest existing coach stop**. Running times are **observed medians** where the
   network already drives the segment, otherwise estimates scaled by the corridor's observed/estimated ratio.
4. **Timetables** both ways: 10-minute dwell, 45-minute break after 4.5 h driving (Reg. (EC) No 561/2006, Art. 7).
5. **Vehicles and drivers**: greedy vehicle blocks with a 45-minute layover; driver duties at 9 h daily
   driving (Art. 6); plus an alternative departure pattern that minimises coaches.
6. **Legal basis and attachments**:
   - two or more EU Member States: Regulation (EC) No 1073/2009, Articles 5–8
   - Germany only: PBefG § 42a with application content per § 12
   - otherwise: national or bilateral rules, to confirm with the authority
7. **Handoff**: open checks with owner roles and status, and the sign-offs required before sales open.

Current example: [Bucharest – Plovdiv](worked-case-bucharest-plovdiv.md).

A planning draft, not a legal filing: stop locations must be agreed locally, and the competent
authority's checklist prevails.
