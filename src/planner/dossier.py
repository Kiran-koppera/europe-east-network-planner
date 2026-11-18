"""Worked planning case and draft line-authorization dossier for a proposed coach line (Word).

For the chosen city pair the dossier answers the questions a planning team asks before a line
goes to partners, authorities and sales:

1. What can a passenger do today? Timed itineraries via every hub, both directions.
2. What would the direct line look like? Real coach stops, observed running times where the
   network already drives a segment, outbound and return timetables.
3. What does it take to run? Vehicle blocks and driver duties.
4. What is the legal route and what must be filed?
5. Handoff: decision, open checks, owners and sign-offs before sales open.

It is a planning draft, not a legal filing: the competent authority's checklist prevails.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

from . import transfers  # noqa: E402
from .config import BREAK_AFTER_H, BREAK_MIN, COACH_SPEED_KMH, ROAD_FACTOR  # noqa: E402
from .geo import haversine_km  # noqa: E402

EU_MEMBERS = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV",
              "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
CORRIDOR_KM = 25
MAX_INTERMEDIATE = 3
DWELL_MIN = 10
MIN_LAYOVER_MIN = 45          # turnaround incl. cleaning and boarding
MAX_DAILY_DRIVING_H = 9.0     # Regulation (EC) No 561/2006, Art. 6 (extendable to 10 h twice a week)
DEPARTURES = ["07:30", "15:00"]


# ----------------------------------------------------------------------------------- legal basis
def legal_basis(countries: list[str]) -> tuple[str, list[str]]:
    cs = set(countries)
    if len(cs) > 1 and cs <= EU_MEMBERS:
        return ("International regular service within the EU: Regulation (EC) No 1073/2009, Articles 5–8. "
                "The application goes to the competent authority of the Member State where the point of "
                "departure is located, which seeks the agreement of the other Member States on the route.",
                ["Copy of the Community licence for the international carriage of passengers by road",
                 "Proposed timetable, frequency, prices and conditions of carriage",
                 "Route map with the stops at which passengers are picked up and set down",
                 "Expected service period and number of vehicles",
                 "Driving and rest time plan showing compliance with Regulation (EC) No 561/2006",
                 "Stop agreements with the municipalities or stop operators"])
    if cs == {"DE"}:
        return ("Domestic long-distance service in Germany: Personenbeförderungsgesetz (PBefG) § 42a, "
                "application content per § 12 (for long-distance services an overview map is sufficient).",
                ["Application form of the competent authority (Genehmigungsbehörde)",
                 "Overview map with stops (§ 12 para. 1 PBefG)", "Timetable",
                 "Documents on reliability, safety and capacity of the operator",
                 "Consent of the local bodies for the requested stops, if requested (§ 12 para. 3)"])
    return ("National or bilateral rules apply (at least one country is outside the EU, or the line is "
            "domestic outside Germany). Confirm the procedure with the competent national authority.",
            ["Authority-specific application form", "Route map with stops", "Timetable",
             "Operator licence and insurance documents", "Driving and rest time plan"])


# ----------------------------------------------------------------------------------- route
def build_route(a: dict, b: dict, places: pd.DataFrame) -> pd.DataFrame:
    """Origin, up to three intermediate network cities near the corridor, destination."""
    pts = places[(places["population"] >= 50_000) & ~places["place_id"].isin([a["place_id"], b["place_id"]])].copy()
    ax, ay, bx, by = a["lon"], a["lat"], b["lon"], b["lat"]
    lat0 = np.radians((ay + by) / 2)
    vx, vy = (bx - ax) * np.cos(lat0), by - ay
    px, py = (pts["lon"] - ax) * np.cos(lat0), pts["lat"] - ay
    t = (px * vx + py * vy) / (vx ** 2 + vy ** 2)
    off_km = np.hypot(px - t * vx, py - t * vy) * 111.2
    pts = pts.assign(t=t, off=off_km)
    pts = pts[(pts["t"] > 0.1) & (pts["t"] < 0.9) & (pts["off"] <= CORRIDOR_KM)]
    pts = pts.sort_values("population", ascending=False).head(MAX_INTERMEDIATE).sort_values("t")
    rows = [a] + pts[["place_id", "place", "country", "population", "lat", "lon"]].to_dict("records") + [b]
    return pd.DataFrame(rows).reset_index(drop=True)


def main_stops(route: pd.DataFrame, stop_places: pd.DataFrame, stop_weekly: pd.Series) -> pd.DataFrame:
    """The busiest existing coach stop in each city (by weekly calls), with its coordinates."""
    sp = stop_places.assign(calls=stop_places["stop_id"].map(stop_weekly).fillna(0).astype(int))
    rows = []
    for r in route.itertuples():
        c = sp[sp["place_id"] == r.place_id].sort_values("calls", ascending=False)
        if len(c):
            s = c.iloc[0]
            rows.append({"stop_id": s.stop_id, "stop": s.stop_name, "stop_lat": s.stop_lat, "stop_lon": s.stop_lon,
                         "weekly_calls": int(s.calls)})
        else:
            rows.append({"stop_id": None, "stop": f"{r.place} (stop to be agreed)", "stop_lat": r.lat,
                         "stop_lon": r.lon, "weekly_calls": 0})
    return pd.concat([route, pd.DataFrame(rows)], axis=1)


TWIN_KM = 15  # two corridor cities closer than this get one stop


def segment_times(route: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    """Running time per segment.

    Observed: median in-vehicle time on today's network for the same city pair. Estimated:
    road km / commercial speed, scaled by the observed / estimated ratio of this corridor's
    observed segments, so hilly or slow roads are not under-estimated.
    """
    rows = []
    for i in range(1, len(route)):
        p, q = route.iloc[i - 1], route.iloc[i]
        km = float(haversine_km(p["stop_lat"], p["stop_lon"], q["stop_lat"], q["stop_lon"])) * ROAD_FACTOR
        obs = legs[((legs["o"] == p["place_id"]) & (legs["d"] == q["place_id"]))
                   | ((legs["o"] == q["place_id"]) & (legs["d"] == p["place_id"]))]
        model = km / COACH_SPEED_KMH * 60
        rows.append({"from": p["place"], "to": q["place"], "road_km_est": round(km), "model": model,
                     "observed": float(obs["minutes"].median()) if len(obs) else None,
                     "runs": int(obs["runs"].sum()) if len(obs) else 0})
    df = pd.DataFrame(rows)
    seen = df.dropna(subset=["observed"])
    seen = seen[seen["road_km_est"] > 20]  # very short hops say little about road speed
    factor = float((seen["observed"] / seen["model"]).median()) if len(seen) else 1.0
    factor = min(max(factor, 0.8), 2.0)
    df["minutes"] = [round(o) if o is not None and not pd.isna(o) else round(m * factor)
                     for o, m in zip(df["observed"], df["model"])]
    df["source"] = [f"observed median of {r} weekly runs" if r else
                    (f"estimated, corridor-calibrated (× {factor:.2f})" if len(seen) else
                     f"estimated ({ROAD_FACTOR} × straight line, {COACH_SPEED_KMH:.0f} km/h)")
                    for r in df["runs"]]
    return df[["from", "to", "road_km_est", "minutes", "source"]]


def pick_twins(route: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    """Where two intermediate cities are within TWIN_KM, keep the one giving more observed segments."""
    route = route.reset_index(drop=True)
    for i in range(1, len(route) - 2):
        if i + 1 >= len(route) - 1:
            break
        p, q = route.iloc[i], route.iloc[i + 1]
        if haversine_km(p["stop_lat"], p["stop_lon"], q["stop_lat"], q["stop_lon"]) < TWIN_KM:
            options = [route.drop(index=i + 1).reset_index(drop=True), route.drop(index=i).reset_index(drop=True)]
            score = [(segment_times(o, legs)["source"].str.startswith("observed").sum(), o["population"].sum())
                     for o in options]
            return pick_twins(options[int(np.argmax([s[0] * 1e9 + s[1] for s in score]))], legs)
    return route


def timetable(stops: list[str], seg_minutes: list[int], departures: list[str]) -> pd.DataFrame:
    """Times at each stop: segment running times, a dwell at intermediate stops, statutory breaks."""
    out = {"Stop": stops}
    for dep in departures:
        h, m = map(int, dep.split(":"))
        t = timedelta(hours=h, minutes=m)
        times, driven = [_hhmm(t)], 0.0
        for i, seg in enumerate(seg_minutes):
            if driven + seg / 60 > BREAK_AFTER_H:
                t += timedelta(minutes=BREAK_MIN)
                driven = 0.0
            t += timedelta(minutes=seg)
            driven += seg / 60
            times.append(_hhmm(t))
            if i < len(seg_minutes) - 1:
                t += timedelta(minutes=DWELL_MIN)
        out[f"Dep. {dep}"] = times
    return pd.DataFrame(out)


def _hhmm(t: timedelta) -> str:
    s = int(t.total_seconds())
    return f"{s // 3600 % 24:02d}:{s % 3600 // 60:02d}"


def _mins(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def vehicle_blocks(out_tt: pd.DataFrame, ret_tt: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    """Chain trips into vehicle workings (greedy, minimum layover at the terminus)."""
    trips = []
    for tt, o, d in ((out_tt, a, b), (ret_tt, b, a)):
        for col in tt.columns[1:]:
            start, end = _mins(tt[col].iloc[0]), _mins(tt[col].iloc[-1])
            end += 1440 if end < start else 0
            trips.append({"from": o, "to": d, "dep": start, "arr": end})
    trips.sort(key=lambda x: x["dep"])
    vehicles: list[list[dict]] = []
    for tr in trips:
        for v in vehicles:
            last = v[-1]
            if last["to"] == tr["from"] and tr["dep"] - last["arr"] >= MIN_LAYOVER_MIN:
                v.append(tr)
                break
        else:
            vehicles.append([tr])
    rows = []
    for i, v in enumerate(vehicles, 1):
        driving = sum(t["arr"] - t["dep"] for t in v) / 60
        hm = lambda m: _hhmm(timedelta(minutes=m))  # noqa: E731
        rows.append({"Vehicle": f"Coach {i}",
                     "Working": " → ".join(f"{t['from']} {hm(t['dep'])}–{hm(t['arr'])}" for t in v),
                     "Scheduled time (h)": round(driving, 1),
                     "Driver duties": max(1, math.ceil(driving / MAX_DAILY_DRIVING_H))})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------- existing options
def existing_options(feed, stop_places, week, a_id: str, b_id: str, hubs: list[str], names: pd.Series,
                     km: float) -> tuple[pd.DataFrame, dict]:
    legs = transfers.timed_legs(feed, stop_places, week[0], week[1] + timedelta(days=1), {a_id, b_id})
    limit = transfers.practical_limit(km)
    rows, best = [], {}
    for tag, (o, d) in {"outbound": (a_id, b_id), "return": (b_id, a_id)}.items():
        conn = transfers.connections(legs, o, d, hubs, last_start=week[1])
        for h in hubs:
            c = conn[conn["hub"] == h]
            miss, retimed = closest_miss(legs, o, d, h, week[1]) if len(c) == 0 else (None, None)
            rows.append({"Direction": f"{names[o]} → {names[d]}", "Hub": names.get(h, h),
                         "Itineraries / week": int(len(c)),
                         "Days with a connection": int(c["date_1"].nunique()) if len(c) else 0,
                         "Fastest (h:mm)": _dur(c["total_min"].min()) if len(c) else "–",
                         "Practical": "yes" if len(c) and c["total_min"].min() <= limit else "no",
                         "Closest miss": miss or "", "_retimed_min": retimed})
        if len(conn):
            r = conn.loc[conn["total_min"].idxmin()]
            best[tag] = {"hub": names.get(r["hub"], r["hub"]), "total_min": int(r["total_min"]),
                         "dep": _hhmm(timedelta(seconds=int(r["dep_1"]) % 86400)), "wait_min": int(r["wait_min"]),
                         "first": r["o_stop_1"], "change": f"{r['d_stop_1']} → {r['o_stop_2']}", "last": r["d_stop_2"],
                         "date": r["date_1"].isoformat()}
    return pd.DataFrame(rows), best


def closest_miss(legs: pd.DataFrame, o: str, d: str, hub: str, last_start: date) -> tuple[str, int | None]:
    """For a hub with no feasible connection: the nearest pair of legs and how far it is from working."""
    first = legs[(legs["o"] == o) & (legs["d"] == hub) & (legs["date"] <= last_start)]
    second = legs[(legs["o"] == hub) & (legs["d"] == d)]
    if first.empty or second.empty:
        return "no leg on one side", None
    best = None
    sdep, sarr = second["dep"].to_numpy(), second["arr"].to_numpy()
    for fdep, arr in zip(first["dep"].to_numpy(), first["arr"].to_numpy()):
        gaps = (sdep - arr) / 60
        for j in np.where((gaps > -240) & (gaps < 24 * 60))[0]:
            g = gaps[j]
            off = (transfers.MIN_TRANSFER_MIN - g) if g < transfers.MIN_TRANSFER_MIN else (g - transfers.MAX_WAIT_MIN)
            if off > 0 and (best is None or off < best[0]):
                best = (off, g, (sarr[j] - fdep) / 60)
    if best is None:
        return "no legs within a day", None
    off, g, total = best
    retimed = int(total - off) if g > transfers.MAX_WAIT_MIN else int(total + off)
    return (f"onward leg leaves {abs(int(g))} min {'before' if g < 0 else 'after'} arrival "
            f"({int(off)} min outside the {transfers.MIN_TRANSFER_MIN}–{transfers.MAX_WAIT_MIN} min window; "
            f"{_dur(total)} end to end as timetabled)"), retimed


def _dur(m) -> str:
    m = int(m)
    return f"{m // 60}:{m % 60:02d}"


# ----------------------------------------------------------------------------------- map
def overview_map(route: pd.DataFrame, network_places: pd.DataFrame, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5), dpi=180)
    pad = 1.0
    y0, y1 = route["lat"].min() - pad, route["lat"].max() + pad
    k = np.cos(np.radians(route["lat"].mean()))
    xc, half = (route["lon"].min() + route["lon"].max()) / 2, (route["lon"].max() - route["lon"].min()) / 2 + pad
    half = max(half, (y1 - y0) * 1.4 / k / 2)
    x0, x1 = xc - half, xc + half
    bg = network_places[network_places["lon"].between(x0, x1) & network_places["lat"].between(y0, y1)]
    ax.scatter(bg["lon"], bg["lat"], s=6, color="#c9bfae", zorder=1, label="Existing network places")
    ax.plot(route["stop_lon"], route["stop_lat"], color="#1f4f7a", lw=2.5, zorder=2, label="Proposed line")
    ax.scatter(route["stop_lon"], route["stop_lat"], s=60, color="#1f4f7a", edgecolor="white", lw=1.5, zorder=3)
    for r in route.itertuples():
        ax.annotate(f"{r.place} ({r.country})", (r.stop_lon, r.stop_lat), xytext=(6, 6), textcoords="offset points",
                    fontsize=8, weight="bold", color="#2a2118")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(1 / k)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(color="#ece5d8", lw=0.6)
    ax.legend(loc="lower right", fontsize=7, frameon=False)
    ax.set_title("Overview map (schematic, straight-line segments between coach stops)", fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _table(doc: Document, df: pd.DataFrame) -> None:
    t = doc.add_table(rows=1, cols=len(df.columns))
    t.style = "Light Grid Accent 1"
    for i, c in enumerate(df.columns):
        t.rows[0].cells[i].text = str(c)
    for row in df.itertuples(index=False):
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = f"{v:,}" if isinstance(v, (int, np.integer)) and abs(v) >= 1000 else str(v)


# ----------------------------------------------------------------------------------- dossier
def build_case(opp: dict, places: pd.DataFrame, *, feed, stop_places, week, legs, pairs, stop_weekly) -> dict:
    """All numbers of the worked case, independent of the Word layout (also used by tests and the site)."""
    p = places.set_index("place_id")
    a = {"place_id": opp["a"], **p.loc[opp["a"], ["place", "country", "population", "lat", "lon"]].to_dict()}
    b = {"place_id": opp["b"], **p.loc[opp["b"], ["place", "country", "population", "lat", "lon"]].to_dict()}
    route = pick_twins(main_stops(build_route(a, b, places), stop_places, stop_weekly), legs)
    segs = segment_times(route, legs)
    out_tt = timetable(route["stop"].tolist(), segs["minutes"].tolist(), DEPARTURES)
    ret_tt = timetable(route["stop"].tolist()[::-1], segs["minutes"].tolist()[::-1], DEPARTURES)
    blocks = vehicle_blocks(out_tt, ret_tt, a["place"], b["place"])
    run_min = _mins(out_tt.iloc[-1, 1]) - _mins(out_tt.iloc[0, 1])
    second = _mins(DEPARTURES[0]) + run_min + MIN_LAYOVER_MIN
    second = int(math.ceil(second / 15) * 15)
    alt_deps = [DEPARTURES[0], _hhmm(timedelta(minutes=second))]
    alt_out = timetable(route["stop"].tolist(), segs["minutes"].tolist(), alt_deps)
    alt_ret = timetable(route["stop"].tolist()[::-1], segs["minutes"].tolist()[::-1], alt_deps)
    alt_blocks = vehicle_blocks(alt_out, alt_ret, a["place"], b["place"])
    nb_a = set(pairs.loc[pairs["a"] == a["place_id"], "b"]) | set(pairs.loc[pairs["b"] == a["place_id"], "a"])
    nb_b = set(pairs.loc[pairs["a"] == b["place_id"], "b"]) | set(pairs.loc[pairs["b"] == b["place_id"], "a"])
    hubs = sorted(nb_a & nb_b)
    options, best = existing_options(feed, stop_places, week, a["place_id"], b["place_id"], hubs,
                                     p["place"], float(opp["km"]))
    direct_min = _mins(out_tt.iloc[-1, 1]) - _mins(out_tt.iloc[0, 1])
    direct_min += 1440 if direct_min < 0 else 0
    return {"a": a, "b": b, "route": route, "segments": segs, "outbound": out_tt, "return": ret_tt,
            "blocks": blocks, "alt_departures": alt_deps, "alt_blocks": alt_blocks,
            "alt_last_arrival": alt_out.iloc[-1, -1], "hubs": [p.at[h, "place"] for h in hubs],
            "options": options, "best": best,
            "direct_min": direct_min, "practical_limit_min": round(transfers.practical_limit(float(opp["km"]))),
            "legal": legal_basis(route["country"].tolist())}


def write_dossier(opp: dict, places: pd.DataFrame, feed_meta: dict, out_dir: Path, **ctx) -> tuple[Path, dict]:
    case = build_case(opp, places, **ctx)
    a, b, route, segs = case["a"], case["b"], case["route"], case["segments"]
    basis, attachments = case["legal"]
    slug = f"{a['place']}-{b['place']}".lower().replace(" ", "-")
    out_dir.mkdir(parents=True, exist_ok=True)
    img = overview_map(route, places, out_dir / f"dossier-{slug}-map.png")
    best = case["best"]
    total_km = int(segs["road_km_est"].sum())
    n_obs = int(segs["source"].str.startswith("observed").sum())

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10.5)
    h = doc.add_heading(f"Worked planning case and line dossier – draft\n{a['place']} – {b['place']}", 0)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT
    note = doc.add_paragraph()
    run = note.add_run(f"Planning draft generated {date.today().isoformat()} from the public timetable feed "
                       f"(valid {feed_meta.get('feed_start_date')}–{feed_meta.get('feed_end_date')}), reference week "
                       f"{feed_meta.get('reference_week', ['', ''])[0]} to {feed_meta.get('reference_week', ['', ''])[1]}. "
                       "Not a legal filing; the competent authority's checklist prevails.")
    run.italic, run.font.color.rgb = True, RGBColor(0x6A, 0x5B, 0x4B)

    doc.add_heading("1. Decision summary", 1)
    ob, rb = best.get("outbound"), best.get("return")
    today = (f"Today the fastest one-change itinerary takes {_dur(ob['total_min'])} outbound (via {ob['hub']}) "
             if ob else "Today there is no one-change itinerary outbound ")
    today += (f"and {_dur(rb['total_min'])} on the return (via {rb['hub']})." if rb else "and none on the return.")
    doc.add_paragraph(
        f"Proposed direct line {a['place']} ({a['country']}) – {b['place']} ({b['country']}): {len(route) - 2} intermediate "
        f"stop(s), about {total_km} road km, {len(DEPARTURES)} departures per day each way, scheduled "
        f"{_dur(case['direct_min'])} end to end. {today} A transfer is treated as practical up to "
        f"{_dur(case['practical_limit_min'])} (2 × the direct coach time + 1 h). The direct line needs "
        f"{len(case['blocks'])} coaches and {int(case['blocks']['Driver duties'].sum())} driver duties per day "
        f"({len(case['alt_blocks'])} coaches if the second departure moves to {case['alt_departures'][1]}).")
    opts = case["options"]
    near = opts[opts["Closest miss"].str.contains(r"\((\d|[1-5]\d) min outside", regex=True)]
    for _, r in near.iterrows():
        rt = r["_retimed_min"]
        verdict = ("would be practical, so test the retiming before committing to a new line"
                   if rt is not None and rt <= case["practical_limit_min"] else
                   f"would still exceed the practical limit of {_dur(case['practical_limit_min'])}, so retiming alone "
                   "does not solve the gap")
        doc.add_paragraph(f"Lower-cost option checked first: {r['Direction']} via {r['Hub']}: {r['Closest miss']}. "
                          f"Retimed to just fit the window it would take {_dur(rt)}, which {verdict}. The direct line "
                          f"takes {_dur(case['direct_min'])}.")
    doc.add_paragraph("Recommendation: take the line to partner and stop feasibility checks (section 7). "
                      "It is not ready for sales until the sign-offs listed there are complete.")

    doc.add_heading("2. What passengers can do today", 1)
    doc.add_paragraph(f"Cities with direct trips to both ends: {', '.join(case['hubs']) or 'none'}. Each was checked "
                      f"against the timetable for every day of the reference week (change time 15–180 min).")
    _table(doc, case["options"].drop(columns="_retimed_min"))
    for tag, label in (("outbound", "Fastest outbound"), ("return", "Fastest return")):
        if best.get(tag):
            x = best[tag]
            doc.add_paragraph(f"{label}: depart {x['first']} {x['dep']} ({x['date']}), change at {x['change']} "
                              f"after {x['wait_min']} min, arrive {x['last']}; {_dur(x['total_min'])} in total.",
                              style="List Bullet")

    doc.add_heading("3. Route, stops and running times", 1)
    _table(doc, route.assign(population=route["population"].astype(int))[
        ["place", "country", "population", "stop", "weekly_calls"]].rename(
        columns={"place": "City", "country": "Country", "population": "Population", "stop": "Coach stop (existing)",
                 "weekly_calls": "Calls / week today"}))
    doc.add_paragraph("")
    _table(doc, segs.rename(columns={"from": "From", "to": "To", "road_km_est": "Road km (est.)",
                                     "minutes": "Minutes", "source": "Source"}))
    doc.add_paragraph(f"{n_obs} of {len(segs)} segments use observed running times from today's network. Estimated "
                      "segments are scaled by how much slower the observed segments of this corridor run than the "
                      "simple estimate; they still need a test drive or a routing check before publication.")
    doc.add_picture(str(img), width=Cm(15.5))

    doc.add_heading("4. Draft timetables", 1)
    doc.add_paragraph(f"Outbound ({a['place']} → {b['place']})")
    _table(doc, case["outbound"])
    doc.add_paragraph(f"Return ({b['place']} → {a['place']})")
    _table(doc, case["return"])
    doc.add_paragraph(f"Assumptions: {DWELL_MIN}-minute dwell at intermediate stops; {BREAK_MIN}-minute break after "
                      f"{BREAK_AFTER_H} h of driving (Regulation (EC) No 561/2006, Art. 7).")

    doc.add_heading("5. Vehicles and drivers", 1)
    _table(doc, case["blocks"])
    doc.add_paragraph(f"Alternative pattern: departures {case['alt_departures'][0]} and {case['alt_departures'][1]} "
                      f"each way let {len(case['alt_blocks'])} coaches cover all four trips (last arrival "
                      f"{case['alt_last_arrival']}), at the cost of a late evening arrival:")
    _table(doc, case["alt_blocks"])
    doc.add_paragraph(f"Minimum layover {MIN_LAYOVER_MIN} min at the terminus. Driver duties assume at most "
                      f"{MAX_DAILY_DRIVING_H:.0f} h driving per day (Regulation (EC) No 561/2006, Art. 6); a driver change "
                      "at the turnaround or a two-driver crew is needed where a working exceeds that.")

    doc.add_heading("6. Legal basis and attachments", 1)
    doc.add_paragraph(basis)
    for item in attachments:
        doc.add_paragraph(item, style="List Bullet")

    doc.add_heading("7. Handoff: open checks, owners and sign-offs", 1)
    handoff = pd.DataFrame([
        [f"Partner operator with Community licence, {len(case['alt_blocks'])}–{len(case['blocks'])} coaches and drivers",
         "Partner management", "Open"],
        [f"Departure slots at {route['stop'].iloc[0]} and {route['stop'].iloc[-1]}", "Stop & station management", "Open"],
        ["Routed running times for estimated segments (test drive or routing engine)", "Network planning", "Open"],
        ["Demand check with booking data for the city pair and today's transfer volumes",
         "Network planning / Revenue", "Open"],
        ["Fares and inventory for the new city pairs", "Pricing", "Open"],
        ["Authorization filed with the competent authority of the departure Member State", "Authorizations / Legal", "Open"],
        ["Customer information, stop pages and timetable publication", "Customer communication", "Open"],
    ], columns=["Check", "Owner (role)", "Status"])
    _table(doc, handoff)
    doc.add_paragraph("Sign-off before sales open: partner contract, stop agreements at every stop, authorization granted "
                      "(or confirmation that operation may start), final timetable and fares.")

    path = out_dir / f"dossier-{slug}.docx"
    doc.save(path)
    return path, case
