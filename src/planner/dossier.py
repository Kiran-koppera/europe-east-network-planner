"""Draft line-authorization dossier for a proposed coach line (Word document).

The dossier collects what an authority typically asks for: route and stops, an overview map, a
timetable, the operating rationale and an attachments checklist. It is a planning draft, not a
legal filing: the competent authority's own checklist always prevails.
"""
from __future__ import annotations

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

from .config import BREAK_AFTER_H, BREAK_MIN, COACH_SPEED_KMH, ROAD_FACTOR  # noqa: E402
from .geo import haversine_km  # noqa: E402

EU_MEMBERS = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV",
              "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
CORRIDOR_KM = 25
MAX_INTERMEDIATE = 3
DWELL_MIN = 10


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
    route = pd.DataFrame(rows)
    seg = haversine_km(route["lat"].shift(), route["lon"].shift(), route["lat"], route["lon"]) * ROAD_FACTOR
    route["km_from_origin"] = seg.fillna(0).cumsum().round(0).astype(int)
    return route


def timetable(route: pd.DataFrame, departures: list[str]) -> pd.DataFrame:
    """Draft times: road km / commercial speed, a dwell at intermediate stops, statutory breaks."""
    out = {"Stop": route["place"].tolist(), "km": route["km_from_origin"].astype(int).tolist()}
    for dep in departures:
        h, m = map(int, dep.split(":"))
        t = timedelta(hours=h, minutes=m)
        times, driven, prev_km = [], 0.0, 0.0
        for i, km in enumerate(route["km_from_origin"]):
            leg_h = (km - prev_km) / COACH_SPEED_KMH
            if driven + leg_h > BREAK_AFTER_H:
                t += timedelta(minutes=BREAK_MIN)
                driven = 0.0
            t += timedelta(hours=leg_h)
            driven += leg_h
            prev_km = km
            label = f"{int(t.total_seconds() // 3600) % 24:02d}:{int(t.total_seconds() % 3600 // 60):02d}"
            times.append(label)
            if 0 < i < len(route) - 1:
                t += timedelta(minutes=DWELL_MIN)
        out[f"Dep. {dep}"] = times
    return pd.DataFrame(out)


def overview_map(route: pd.DataFrame, network_places: pd.DataFrame, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5), dpi=180)
    pad = 1.0
    y0, y1 = route["lat"].min() - pad, route["lat"].max() + pad
    k = np.cos(np.radians(route["lat"].mean()))
    xc, half = (route["lon"].min() + route["lon"].max()) / 2, (route["lon"].max() - route["lon"].min()) / 2 + pad
    half = max(half, (y1 - y0) * 1.4 / k / 2)  # keep a landscape frame
    x0, x1 = xc - half, xc + half
    bg = network_places[network_places["lon"].between(x0, x1) & network_places["lat"].between(y0, y1)]
    ax.scatter(bg["lon"], bg["lat"], s=6, color="#b8c4d0", zorder=1, label="Existing network places")
    ax.plot(route["lon"], route["lat"], color="#0b5cad", lw=2.5, zorder=2, label="Proposed line")
    ax.scatter(route["lon"], route["lat"], s=60, color="#0b5cad", edgecolor="white", lw=1.5, zorder=3)
    for r in route.itertuples():
        ax.annotate(f"{r.place} ({r.country})", (r.lon, r.lat), xytext=(6, 6), textcoords="offset points",
                    fontsize=8, weight="bold", color="#13263b")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(1 / np.cos(np.radians(route["lat"].mean())))
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(color="#e6ebf0", lw=0.6)
    ax.legend(loc="lower right", fontsize=7, frameon=False)
    ax.set_title("Overview map (schematic, straight-line segments)", fontsize=9)
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


def write_dossier(opp: dict, places: pd.DataFrame, feed_meta: dict, out_dir: Path,
                  departures: list[str] | None = None) -> Path:
    departures = departures or ["07:30", "15:00"]
    p = places.set_index("place_id")
    a = {"place_id": opp["a"], **p.loc[opp["a"], ["place", "country", "population", "lat", "lon"]].to_dict()}
    b = {"place_id": opp["b"], **p.loc[opp["b"], ["place", "country", "population", "lat", "lon"]].to_dict()}
    route = build_route(a, b, places)
    tt = timetable(route, departures)
    basis, attachments = legal_basis(route["country"].tolist())
    slug = f"{a['place']}-{b['place']}".lower().replace(" ", "-")
    out_dir.mkdir(parents=True, exist_ok=True)
    img = overview_map(route, places, out_dir / f"dossier-{slug}-map.png")

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10.5)
    h = doc.add_heading(f"Line authorization dossier – draft\n{a['place']} – {b['place']}", 0)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT
    note = doc.add_paragraph()
    run = note.add_run(f"Planning draft generated on {date.today().isoformat()} from the public timetable feed "
                       f"(valid {feed_meta.get('feed_start_date')}–{feed_meta.get('feed_end_date')}). "
                       "Not a legal filing; the competent authority's checklist prevails.")
    run.italic, run.font.color.rgb = True, RGBColor(0x5A, 0x67, 0x75)

    doc.add_heading("1. Summary", 1)
    total_km = int(route["km_from_origin"].iloc[-1])
    doc.add_paragraph(
        f"Proposed regular coach line {a['place']} ({a['country']}) – {b['place']} ({b['country']}), "
        f"about {total_km} road km, {len(route) - 2} intermediate stop(s), {len(departures)} departures per day "
        f"in each direction. Today the pair has status '{opp['status']}' with {opp['weekly_departures']} direct "
        f"weekly departures; {opp['transfer_hubs']} network cities offer a change between the two. "
        f"Demand index {opp['demand_index']} (rank {opp['rank']} of all Europe East opportunities).")

    doc.add_heading("2. Legal basis and procedure", 1)
    doc.add_paragraph(basis)

    doc.add_heading("3. Route and stops", 1)
    stops = route.assign(population=route["population"].astype(int),
                         coordinates=route["lat"].round(4).astype(str) + ", " + route["lon"].round(4).astype(str))
    _table(doc, stops[["place", "country", "population", "km_from_origin", "coordinates"]]
           .rename(columns={"place": "Stop (city)", "country": "Country", "population": "Population",
                            "km_from_origin": "Road km", "coordinates": "Lat, lon"}))
    doc.add_paragraph("Exact stop locations within each city must be agreed with the municipality or stop operator.")

    doc.add_heading("4. Overview map", 1)
    doc.add_picture(str(img), width=Cm(15.5))

    doc.add_heading("5. Draft timetable (outbound)", 1)
    _table(doc, tt)
    doc.add_paragraph(f"Assumptions: road distance = {ROAD_FACTOR} × straight-line distance, {COACH_SPEED_KMH:.0f} km/h "
                      f"commercial speed, {DWELL_MIN}-minute dwell at intermediate stops, {BREAK_MIN}-minute break "
                      f"after {BREAK_AFTER_H} h of driving (Regulation (EC) No 561/2006, Art. 7). Return trips mirror "
                      "the outbound pattern.")

    doc.add_heading("6. Demand rationale", 1)
    doc.add_paragraph(
        f"Populations: {a['place']} {int(a['population']):,}, {b['place']} {int(b['population']):,} (GeoNames). "
        f"Straight-line distance {opp['km']:.0f} km, within the {150}–{1200} km range where coach travel competes well. "
        "The demand index is a gravity model (population × population / distance²) scaled so that the strongest "
        "candidate pair in the region scores 100. It ranks potential; it does not forecast passengers.")

    doc.add_heading("7. Attachments checklist", 1)
    for item in attachments:
        doc.add_paragraph(item, style="List Bullet")

    path = out_dir / f"dossier-{slug}.docx"
    doc.save(path)
    return path
