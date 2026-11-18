# Line-authorization dossier

`python -m planner run` writes a draft dossier (`.docx`) and an overview map (`.png`) for the
highest-ranked opportunity between two cities that are already on the network, preferring an
intra-EU cross-border pair.

## Contents

1. **Summary**: line, road km, stops, departures, today's status and demand rank
2. **Legal basis**, chosen from the countries on the line:
   - two or more EU Member States: Regulation (EC) No 1073/2009, Articles 5–8 (international regular
     services; application to the authority of the Member State of departure)
   - Germany only: Personenbeförderungsgesetz § 42a, application content per § 12 (an overview map is
     sufficient for long-distance services)
   - otherwise: national or bilateral rules, to be confirmed with the authority
3. **Route and stops**: up to three intermediate network cities (≥ 50,000 people) within 25 km of the
   straight corridor, with population, road km and coordinates
4. **Overview map**
5. **Draft timetable**: road km = 1.25 × straight-line km, 70 km/h commercial speed, 10-minute dwell,
   45-minute break after 4.5 h of driving (Regulation (EC) No 561/2006, Art. 7)
6. **Demand rationale**: populations, distance band, index definition
7. **Attachments checklist** for the chosen procedure

## Example

Bucharest – Plovdiv via Ruse and Veliko Tarnovo, 351 road km, departures 07:30 and 15:00, arriving
13:35 and 21:05. [Download](https://kiran-koppera.github.io/europe-east-network-planner/data/dossier-bucharest-plovdiv.docx).

This is a planning draft, not a legal filing. Exact stop locations must be agreed with municipalities
or stop operators, and the competent authority's checklist prevails.
