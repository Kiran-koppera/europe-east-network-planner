/* Europe East Coach Network Planner: renders the JSON written by `python -m planner run`. */
(async function () {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (n, d = 0) => (n == null ? "–" : Number(n).toLocaleString("en-GB", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const pct = (x, d = 0) => (x == null ? "–" : (x * 100).toFixed(d) + "%");
  const get = (f) => fetch("data/" + f).then((r) => r.json());
  const [meta, net, opps, uns, countries, quality, changes, top] = await Promise.all(
    ["meta.json", "network.json", "opportunities.json", "unserved.json", "countries.json", "quality.json", "changelog.json", "top_pairs.json"].map(get));
  const M = meta.metrics, F = meta.meta;
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const ymd = (s) => (s && s.length === 8 ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : s);

  $("#snap").innerHTML = [`Snapshot ${F.snapshot_date}`, `Feed ${ymd(F.feed_start_date)} → ${ymd(F.feed_end_date)}`,
    `Reference week ${F.reference_week[0]} → ${F.reference_week[1]}`].map((t) => `<span>${esc(t)}</span>`).join("<span aria-hidden=\"true\">·</span>");

  // KPIs
  const E = M.europe_east, Q = M.quality, D = M.demand;
  const kpis = [
    ["Countries served", E.countries_served, `of 15 in Europe East`],
    ["Cities on network", fmt(E.places), `${E.cities_100k_served} with ≥100k people`],
    ["Weekly departures", fmt(E.weekly_trip_departures), "trips starting in Europe East"],
    ["Direct city pairs", fmt(E.city_pairs), `${pct(E.cross_border_share)} cross-border`],
    ["Data quality", Q.pass_rate.toFixed(2) + "%", `${fmt(Q.records_checked)} records, ${Q.checks} checks`],
    ["Demand model fit", "ρ = " + (D.spearman ?? "–"), `rank correlation on ${fmt(D.served_pairs)} served pairs`],
  ];
  $("#kpis").innerHTML = kpis.map(([l, v, n]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="n">${n}</div></div>`).join("");

  // Map
  const map = L.map("leaflet", { preferCanvas: true, zoomSnap: 0.5 }).setView([48.6, 22.5], 5);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 12, className: "tiles",
  }).addTo(map);
  const P = Object.fromEntries(net.places.map((p) => [p.id, p]));
  const netLayer = L.layerGroup(), oppLayer = L.layerGroup(), unsLayer = L.layerGroup(), hiLayer = L.layerGroup().addTo(map);
  const segs = net.segments.slice().sort((a, b) => a[2] - b[2]);
  for (const [a, b, w] of segs) {
    const pa = P[a], pb = P[b];
    if (!pa || !pb) continue;
    const cls = w >= 70 ? ["--l3", 3.2] : w >= 14 ? ["--l2", 2] : ["--l1", 1.2];
    L.polyline([[pa.y, pa.x], [pb.y, pb.x]], { color: css(cls[0]), weight: cls[1], opacity: 0.9 })
      .bindTooltip(`${esc(pa.n)} – ${esc(pb.n)}: <b>${w}</b> runs/week`, { sticky: true }).addTo(netLayer);
  }
  for (const p of net.places.filter((p) => p.ee)) {
    L.circleMarker([p.y, p.x], { radius: p.w > 300 ? 5 : p.w > 60 ? 3.5 : 2.2, color: css("--brand"), weight: 1, fillColor: css("--surface"), fillOpacity: 1 })
      .bindPopup(`<b>${esc(p.n)}</b> (${p.c})<br>${fmt(p.w)} weekly departures<br>${p.d} direct destinations${p.p ? `<br>Population ${fmt(p.p)}` : ""}`).addTo(netLayer);
  }
  const oppLine = (o, style) => L.polyline([[o.a_lat, o.a_lon], [o.b_lat, o.b_lon]], style);
  opps.slice(0, 20).forEach((o) => oppLine(o, { color: css("--accent"), weight: 2, dashArray: "6 6", opacity: 0.85 })
    .bindTooltip(`#${o.rank} ${esc(o.a_name)} – ${esc(o.b_name)} · index ${o.demand_index}`, { sticky: true }).addTo(oppLayer));
  uns.forEach((c) => L.circleMarker([c.lat, c.lon], { radius: 5, color: css("--uns"), weight: 2, fill: false })
    .bindTooltip(`${esc(c.name)} (${c.country}) · ${fmt(c.population)} people · no stop within 12 km`).addTo(unsLayer));
  const layers = { "#t-net": netLayer, "#t-opp": oppLayer, "#t-uns": unsLayer };
  for (const [id, layer] of Object.entries(layers)) {
    layer.addTo(map);
    $(id).addEventListener("change", (e) => (e.target.checked ? layer.addTo(map) : map.removeLayer(layer)));
  }

  // Opportunity list
  const STATUS = ["No service: city not on network", "No direct service", "No practical transfer",
    "Practical transfer (one direction)", "Practical transfer", "Linked via hub (untimed)", "Low frequency"];
  const TAG = { 0: "t0", 1: "t1", 2: "t1", 3: "t2", 4: "t2", 5: "t3", 6: "t3" };
  const statusClass = (s) => TAG[STATUS.indexOf(s)] || "t3";
  const hm = (m) => (m == null ? "" : `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`);
  const transferNote = (o) => {
    const parts = [];
    if (o.best_ab_min != null) parts.push(`→ ${hm(o.best_ab_min)} via ${o.best_ab_hub}`);
    if (o.best_ba_min != null) parts.push(`← ${hm(o.best_ba_min)} via ${o.best_ba_hub}`);
    return parts.length ? ` · best change ${parts.join(", ")}` : "";
  };
  STATUS.forEach((s) => $("#f-status").insertAdjacentHTML("beforeend", `<option>${esc(s)}</option>`));
  function renderOpps() {
    const fs = $("#f-status").value, on = $("#f-onnet").checked;
    const rows = opps.filter((o) => (!fs || o.status === fs) && (!on || o.status !== STATUS[0]));
    $("#opps").innerHTML = rows.map((o) => `
      <li class="opp" tabindex="0" data-r="${o.rank}">
        <span class="r">#${o.rank}</span>
        <span class="p">${esc(o.a_name)} – ${esc(o.b_name)}<small>${o.a_country}–${o.b_country} · ${fmt(o.km)} km${esc(transferNote(o))}</small>
          <span class="tag ${statusClass(o.status)}">${esc(o.status)}</span></span>
        <span class="s">${fmt(o.demand_index, 1)}<small>index</small></span>
      </li>`).join("") || `<li class="note">No pairs match these filters.</li>`;
    $("#opps").querySelectorAll(".opp").forEach((li) => {
      const show = () => {
        const o = opps.find((x) => x.rank === +li.dataset.r);
        $("#opps").querySelectorAll(".opp").forEach((x) => x.classList.toggle("on", x === li));
        hiLayer.clearLayers();
        const l = oppLine(o, { color: css("--accent"), weight: 4.5, opacity: 1 }).addTo(hiLayer);
        [[o.a_lat, o.a_lon, o.a_name], [o.b_lat, o.b_lon, o.b_name]].forEach(([y, x, n]) =>
          L.circleMarker([y, x], { radius: 6, color: css("--accent"), fillColor: css("--surface"), fillOpacity: 1, weight: 2.5 })
            .bindTooltip(esc(n), { permanent: true, direction: "top", offset: [0, -6] }).addTo(hiLayer));
        map.flyToBounds(l.getBounds().pad(0.6), { duration: 0.6 });
      };
      li.addEventListener("click", show);
      li.addEventListener("keydown", (e) => e.key === "Enter" && show());
    });
  }
  $("#f-status").addEventListener("change", renderOpps);
  $("#f-onnet").addEventListener("change", renderOpps);
  renderOpps();

  // Country table
  let names;
  try { names = new Intl.DisplayNames(["en"], { type: "region" }); } catch (e) { names = null; }
  const regionName = (cc) => { try { return names ? names.of(cc) : cc; } catch (e) { return cc; } };
  const maxDep = Math.max(...countries.map((c) => c.weekly_trip_departures));
  const cols = [["country", "Country"], ["stops", "Stops", 1], ["places_served", "Cities", 1], ["cities_100k_served", "Cities ≥100k", 1],
    ["weekly_trip_departures", "Weekly departures", 1], ["routes_starting", "Routes", 1], ["city_pairs", "City pairs", 1], ["cross_border_share", "Cross-border", 1]];
  $("#tbl-countries").innerHTML = `<thead><tr>${cols.map(([, n, r]) => `<th class="${r ? "n" : ""}">${n}</th>`).join("")}</tr></thead><tbody>` +
    countries.map((c) => `<tr class="${c.europe_east ? "ee" : ""}">${cols.map(([k, , r]) => {
      if (k === "country") return `<td>${esc(regionName(c[k]))} <span class="cc">${esc(c[k])}</span></td>`;
      if (k === "cross_border_share") return `<td class="n">${pct(c[k])}</td>`;
      if (k === "weekly_trip_departures") return `<td class="n">${fmt(c[k])}<span class="bar" style="width:${(60 * c[k] / maxDep).toFixed(1)}px"></span></td>`;
      return `<td class="${r ? "n" : ""}">${esc(fmt(c[k]) === "NaN" ? c[k] : (r ? fmt(c[k]) : c[k]))}</td>`;
    }).join("")}</tr>`).join("") + "</tbody>";

  // Quality
  $("#q-sub").textContent = `${quality.checks} checks over ${fmt(quality.records_checked)} records; ${fmt(quality.records_flagged)} flagged.`;
  const qp = $("#q-pill");
  qp.textContent = quality.errors ? `${quality.errors} errors` : quality.warnings ? `${quality.warnings} warning${quality.warnings > 1 ? "s" : ""}, 0 errors` : "All checks passed";
  qp.className = "pill " + (quality.errors ? "warn" : "ok");
  $("#checks").innerHTML = quality.results.map((c) => {
    const ic = c.passed ? ["ok", "✓"] : c.severity === "error" ? ["bad", "✕"] : ["warn", "!"];
    return `<li><span class="ic ${ic[0]}">${ic[1]}</span><span>${esc(c.title)}</span><span class="ct">${fmt(c.failed)} / ${fmt(c.checked)}</span>
      ${!c.passed && c.examples.length ? `<span class="ex">e.g. ${c.examples.slice(0, 3).map(esc).join("; ")}</span>` : ""}</li>`;
  }).join("");

  // Changelog
  const S = changes.summary;
  const LABEL = { place_added: "City added", place_removed: "City removed", stop_added: "Stop added", stop_removed: "Stop removed",
    pair_added: "Direct pair added", pair_removed: "Direct pair removed", frequency_up: "Frequency up", frequency_down: "Frequency down" };
  $("#c-sub").textContent = changes.baseline ? `Baseline snapshot ${changes.to}. Changes appear from the next weekly run.`
    : changes.comparable ? `Snapshots ${changes.from} → ${changes.to}, both measured on the week of ${changes.week}.`
    : (changes.note || "Snapshots do not cover a common week.");
  $("#changelog").innerHTML = `<div class="chg">
    <div><b>${S.stops_added ?? 0}/${S.stops_removed ?? 0}</b><span>stops added / removed</span></div>
    <div><b>${S.pairs_added}/${S.pairs_removed}</b><span>direct pairs added / removed</span></div>
    <div><b>${S.frequency_up}/${S.frequency_down}</b><span>frequency up / down (≥7/wk)</span></div></div>` +
    (changes.events.length ? `<div class="table-wrap short" style="margin-top:10px"><table><thead><tr><th>Change</th><th>Item</th><th class="n">Weekly</th></tr></thead><tbody>${changes.events.slice(0, 60).map((e) =>
      `<tr><td>${esc(LABEL[e.type] || e.type)}</td><td>${esc(e.item)}</td><td class="n">${e.from != null && e.to != null ? `${e.from} → ${e.to}` : e.to ?? e.from ?? ""}</td></tr>`).join("")}</tbody></table></div>` : "");
  $("#tbl-top").innerHTML = `<thead><tr><th>City pair</th><th class="n">km</th><th class="n">Weekly</th><th class="n">Fastest</th></tr></thead><tbody>` +
    top.slice(0, 15).map((t) => `<tr><td>${esc(t.a_name)} – ${esc(t.b_name)}</td><td class="n">${fmt(t.km)}</td><td class="n">${fmt(t.weekly_departures)}</td><td class="n">${Math.floor(t.fastest_min / 60)}h${String(t.fastest_min % 60).padStart(2, "0")}</td></tr>`).join("") + "</tbody>";

  // Downloads
  const dl = [
    ["XLSX", "europe-east-network-report.xlsx", "Network report pack", "Summary, data quality, country KPIs, city pairs, opportunities, changelog"],
    ["XLSX", "data-quality-issue-tracker.xlsx", "Data-quality issue tracker", "Speed exceptions by stop pair: lookups, formula flags, owner and status dropdowns, summary"],
  ];
  if (meta.dossier) {
    dl.push(["DOCX", meta.dossier.file, `Worked case: ${meta.dossier.pair}`, "Today's timed options, real stops, timetables both ways, vehicles, legal basis, handoff"]);
    dl.push(["PNG", meta.dossier.file.replace(".docx", "-map.png"), "Dossier overview map", "Schematic map of the proposed line"]);
  }
  $("#dl").innerHTML = dl.map(([x, f, t, d]) => `<a class="dl" href="data/${f}" download><span class="ext">${x}</span><span><b>${esc(t)}</b><span>${esc(d)}</span></span></a>`).join("");
})();
