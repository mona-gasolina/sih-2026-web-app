/* Heat Intelligence – web dashboard.
   Reads the FastAPI backend (same numbers as the desktop app, via service.py)
   and mirrors the desktop dashboard: tiles, map, alert + priority lists and
   district details. Colours come from GET /ui/config so both apps match. */
"use strict";

const API = "..";                        // the page is served at /app/, the API at /
const LIVE_POLL_MS = 5 * 60 * 1000;      // the server itself recomputes hourly
const CODE_NAMES = { GREEN: "No heat wave", YELLOW: "Yellow alert", ORANGE: "Orange alert", RED: "Red alert" };
const MODEL_NAMES = { ecmwf_ifs025: "ECMWF", gfs_seamless: "GFS", icon_seamless: "ICON" };
const CODE_RANK = { GREEN: 0, YELLOW: 1, ORANGE: 2, RED: 3 };
const DARK_TEXT = "#0F172A";

const state = {
  config: null,
  user: null,
  mapBuilt: false,
  pollTimer: null,
  theme: "light",
  layer: "temperature",
  replay: "",
  districts: [],        // /districts summaries, most urgent first
  byName: new Map(),
  alerts: [],
  selected: null,
  detailToken: 0,
  map: null,
  geoLayer: null,
  shapes: new Map(),    // district name → Leaflet layer
};

const $ = (sel) => document.querySelector(sel);

// ------------------------------------------------------------------ helpers
function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
const round = (v) => Math.round(Number(v));
const titleCase = (s) => String(s || "").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());

function storageGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
function storageSet(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } }

function formatPopulation(v) {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 100_000) return `${(v / 100_000).toFixed(2)}L`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

async function getJSON(path, options = {}) {
  const response = await fetch(`${API}${path}`, { credentials: "same-origin", ...options });
  if (response.status === 401 && !path.startsWith("/auth/")) sessionEnded();
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch { /* not JSON */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
const withReplay = (path) => (state.replay ? `${path}${path.includes("?") ? "&" : "?"}replay=${encodeURIComponent(state.replay)}` : path);

// ------------------------------------------------------------------ colours (same maths as config.py)
function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbToHex([r, g, b]) {
  return "#" + [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("").toUpperCase();
}
function mix(a, b, t) {
  const A = hexToRgb(a), B = hexToRgb(b);
  return rgbToHex(A.map((v, i) => v + (B[i] - v) * t));
}
function interpolate(stops, value) {
  if (value <= stops[0][0]) return stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    const [v1, c1] = stops[i];
    const [v0, c0] = stops[i - 1];
    if (value <= v1) return mix(c0, c1, (value - v0) / (v1 - v0));
  }
  return stops[stops.length - 1][1];
}
function luminance(hex) {
  return hexToRgb(hex).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
    .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
}
function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}
function contrastText(bg) { return contrast(bg, "#FFFFFF") > contrast(bg, DARK_TEXT) ? "#FFFFFF" : DARK_TEXT; }
/** Two gradient ends plus a text colour that passes WCAG AA on both (config.readable_gradient). */
function readableGradient(start, end) {
  for (let i = 0; i < 12; i++) {
    let best = null, score = 0;
    for (const text of ["#FFFFFF", DARK_TEXT]) {
      const s = Math.min(contrast(start, text), contrast(end, text));
      if (s > score) { best = text; score = s; }
    }
    if (score >= 4.5) return [start, end, best];
    start = mix(start, "#000000", 0.035);
    end = mix(end, "#000000", 0.035);
  }
  return [start, end, "#FFFFFF"];
}
const tempColour = (t) => interpolate(state.config.temperature_stops, t);
const riskColour = (s) => interpolate(state.config.risk_stops, Math.max(0, Math.min(100, s)));
const bandColour = (band) => state.config.band_colours[band] || "#94A3B8";
const bandLabel = (band) => state.config.band_labels?.[band] || titleCase(band);
const bandAdvice = (band) => state.config.band_advice?.[band] || "";
const stressLabel = (category) => state.config.stress_labels?.[category] || category;
const temperatureGradient = (t) => readableGradient(tempColour(t - 2.5), tempColour(t + 2.5));
function chip(text, band) {
  const colour = bandColour(band);
  return `<span class="chip" style="background:${colour};color:${contrastText(colour)}">${esc(text)}</span>`;
}

// ------------------------------------------------------------------ theme
const SUN_ICON = `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/></svg>`;
const MOON_ICON = `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></svg>`;
function applyTheme(name) {
  state.theme = name;
  document.documentElement.dataset.theme = name;
  const tokens = state.config?.themes?.[name] || {};
  for (const [key, value] of Object.entries(tokens)) document.documentElement.style.setProperty(`--${key}`, value);
  $("#theme").setAttribute("aria-checked", String(name === "dark"));     // a switch: shows the current mode
  $("#login-theme").innerHTML = name === "dark" ? SUN_ICON : MOON_ICON;   // drawn, not font symbols
  $("#login-theme").title = name === "dark" ? "Switch to light mode" : "Switch to dark mode";
  if (state.geoLayer) paintMap();
}

// ------------------------------------------------------------------ map
function districtName(feature) {
  const p = feature.properties || {};
  for (const key of ["district", "District", "DISTRICT", "NAME_2", "name", "NAME"]) if (p[key]) return String(p[key]);
  return "";
}

async function buildMap() {
  // On phones one-finger drags scroll the page, not the map (pinch or +/− to zoom).
  state.map = L.map("map", { zoomSnap: 0.25, attributionControl: false, scrollWheelZoom: false,
                             dragging: !L.Browser.mobile, tap: false });
  const geo = await getJSON("/geojson");
  state.geoLayer = L.geoJSON(geo, {
    style: () => ({ weight: 1, color: "#475569", fillOpacity: 0.9, fillColor: "#CBD5E1" }),
    onEachFeature: (feature, layer) => {
      const name = districtName(feature);
      state.shapes.set(name, layer);
      layer.bindTooltip(() => tooltipHtml(name), { sticky: true, className: "district-tip", direction: "top", offset: [0, -8] });
      layer.on("mouseover", () => layer.setStyle({ weight: 2.5 }));
      layer.on("mouseout", () => paintShape(name));
      layer.on("click", () => selectDistrict(name));
    },
  }).addTo(state.map);
  fitMap();
  new ResizeObserver(() => { state.map.invalidateSize(); fitMap(); }).observe($("#map"));
}
function fitMap() {
  // While the dashboard is hidden (sign-in page) the map is 0×0; fitting then leaves
  // Leaflet with no valid zoom and a blank map after the next sign-in.
  const box = $("#map");
  if (!state.geoLayer || !box.clientWidth || !box.clientHeight) return;
  state.map.fitBounds(state.geoLayer.getBounds(), { padding: [10, 10] });
}

function tooltipHtml(name) {
  const d = state.byName.get(name);
  if (!d) return `<b>${esc(name)}</b><br>Getting the forecast…`;
  return `<b>${esc(name)}</b><br>${round(d.temperature)}°C now · feels like ${round(d.feels_like_now)}°<br>` +
         `Peak today: ${esc(bandLabel(d.heat_stress_band).toLowerCase())} · ${esc(CODE_NAMES[d.imd_code] || d.imd_code)}`;
}

function paintShape(name) {
  const layer = state.shapes.get(name);
  if (!layer) return;
  const d = state.byName.get(name);
  const fill = !d ? (state.theme === "dark" ? "#22304D" : "#CBD5E1")
    : state.layer === "risk" ? riskColour(d.relative_risk) : tempColour(d.temperature);
  const selected = name === state.selected;
  layer.setStyle({
    fillColor: fill,
    color: selected ? (state.theme === "dark" ? "#FFFFFF" : DARK_TEXT) : (state.theme === "dark" ? "#0B1220" : "#475569"),
    weight: selected ? 3.5 : 1,
  });
  if (selected) layer.bringToFront();
}
function paintMap() {
  for (const name of state.shapes.keys()) paintShape(name);
  drawLegend();
}

function drawLegend() {
  const vertical = window.matchMedia("(min-width: 861px)").matches;
  let stops, ticks, title;
  if (state.layer === "risk") {
    stops = state.config.risk_stops.map(([v, c]) => [v / 100, c]);
    ticks = state.config.risk_stops.map(([v]) => String(v));
    title = "Today's relative risk (0–100)";
  } else {
    const s = state.config.temperature_stops, lo = s[0][0], hi = s[s.length - 1][0];
    stops = s.map(([t, c]) => [(t - lo) / (hi - lo), c]);
    ticks = s.map(([t]) => `${t}°`);
    ticks[0] = `≤${lo}°`; ticks[ticks.length - 1] = `${hi}°+`;
    title = "Air temperature now (°C)";
  }
  const dir = vertical ? "to top" : "to right";
  const gradient = `linear-gradient(${dir}, ${stops.map(([p, c]) => `${c} ${(p * 100).toFixed(1)}%`).join(", ")})`;
  if (vertical) ticks = ticks.slice().reverse();
  $("#legend").innerHTML = `<h3>${title}</h3><div class="scale"><div class="bar" style="background:${gradient}"></div>` +
    `<div class="ticks">${ticks.map((t) => `<span>${t}</span>`).join("")}</div></div>`;
}

// ------------------------------------------------------------------ data
async function loadData({ quiet = false } = {}) {
  if (!quiet) {
    $("#updated").textContent = state.replay ? "Loading the replay…" : "Getting the forecast…";
    $("#kpis").classList.add("loading");
  }
  try {
    const [districts, alerts] = await Promise.all([getJSON(withReplay("/districts")), getJSON(withReplay("/alerts"))]);
    state.districts = districts.districts;
    state.byName = new Map(state.districts.map((d) => [d.district, d]));
    state.alerts = alerts.alerts;
    $("#error-banner").hidden = true;
    renderAll(districts);
  } catch (error) {
    if (error.status === 401) return;    // sessionEnded() already showed the sign-in page
    if (error.status === 503) {          // first forecast still downloading, or no weather at all
      const loading = /loading/i.test(error.message);
      $("#updated").textContent = loading ? "The server is getting the forecast…" : "Live weather unavailable";
      $("#error-banner").textContent = error.message;
      $("#error-banner").hidden = loading;
      setTimeout(() => loadData({ quiet: true }), loading ? 5000 : 30000);
      return;
    }
    $("#error-banner").textContent = `Could not load the heat data: ${error.message}. Is the API running (python api.py)?`;
    $("#error-banner").hidden = false;
    $("#updated").textContent = "Not connected";
  }
}

function renderAll(meta) {
  const when = new Date(meta.weather_time);
  const time = isNaN(when) ? "" : when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  $("#kpis").classList.remove("loading");
  const offline = String(meta.source || "").includes("offline") || meta.source === "DEMO";
  $("#updated").textContent = state.replay ? "Replay – past weather"
    : meta.source === "DEMO" ? "Offline – showing sample data"
    : offline ? `Offline – forecast from ${time}` : `Forecast updated ${time}`;
  const label = [...$("#source").options].find((o) => o.value === state.replay)?.textContent || "";
  $("#replay-banner").hidden = !state.replay;
  $("#replay-banner").textContent = `Replaying the ${label.replace(/^Replay:\s*/, "")} – past weather, not a live forecast. Nothing is sent to officers.`;
  $("#refresh").disabled = !!state.replay;
  $("#status-text").textContent = state.replay ? "Past weather (replay)" : "Forecast updates hourly";

  renderKpis();
  renderAlerts();
  renderPriority();
  renderDistrictSelect();
  paintMap();
  if (!state.selected || !state.byName.has(state.selected)) {
    const home = [...state.byName.keys()].find((n) => n.toLowerCase() === String(state.user?.district || "").toLowerCase());
    state.selected = home || (state.byName.has("Chennai") ? "Chennai" : state.districts[0]?.district);
  }
  if (state.selected) selectDistrict(state.selected, { keepScroll: true });
}

function setKpi(id, value, sub, colour) {
  const tile = $(id);
  tile.querySelector(".value").textContent = value;
  tile.querySelector(".sub").textContent = sub;
  tile.style.borderLeftColor = colour;
}

function renderKpis() {
  const all = state.districts;
  if (!all.length) return;
  const heat = all.filter((d) => d.imd_code !== "GREEN");
  const worst = heat.reduce((w, d) => (CODE_RANK[d.imd_code] > CODE_RANK[w] ? d.imd_code : w), "GREEN");
  setKpi("#kpi-heatwaves", `${heat.length} / ${all.length}`,
    heat.length ? `districts · worst: ${worst.toLowerCase()} alert` : "districts, next 5 days", bandColour(worst));
  const hot = all.reduce((a, b) => (b.temperature > a.temperature ? b : a));
  setKpi("#kpi-hottest", `${round(hot.temperature)}°C`, hot.district, tempColour(hot.temperature));
  const feels = all.reduce((a, b) => (b.feels_like_peak_5day > a.feels_like_peak_5day ? b : a));
  setKpi("#kpi-feels", `${round(feels.feels_like_peak_5day)}°C`, `${feels.district} • ${feels.feels_like_peak_day}`,
    tempColour(feels.feels_like_peak_5day - 4));
  const people = heat.reduce((sum, d) => sum + (d.population_2011 || 0), 0);
  setKpi("#kpi-people", people ? formatPopulation(people) : "0", "in heat-wave districts", bandColour(people ? worst : "GREEN"));
  const warnings = state.alerts.filter((a) => a.level === "WARNING").length;
  setKpi("#kpi-alerts", `${warnings} warning${warnings === 1 ? "" : "s"}`, `${state.alerts.length - warnings} on watch`,
    bandColour(state.alerts[0]?.colour || "GREEN"));
}

function rowButton(name, inner) {
  return `<button type="button" class="row" title="${esc(name)}" data-district="${esc(name)}"${name === state.selected ? ' aria-current="true"' : ""}>${inner}</button>`;
}

function renderAlerts() {
  const box = $("#alerts");
  if (!state.alerts.length) {
    box.innerHTML = `<p class="muted small">No heat wave expected in the next 5 days.</p>`;
    return;
  }
  box.innerHTML = state.alerts.slice(0, 8).map((a) => rowButton(a.district,
    `<span class="name">${esc(a.district)}<small>${esc(titleCase(a.colour))} alert · from ${esc(a.day)}</small></span>` +
    chip(titleCase(a.level), a.colour))).join("") +
    (state.alerts.length > 8 ? `<p class="muted small">+ ${state.alerts.length - 8} more</p>` : "");
}

function renderPriority() {
  const anyHeatWave = state.districts.some((d) => d.imd_code !== "GREEN");
  $("#priority-title").textContent = anyHeatWave ? "Priority districts" : "Highest heat stress";
  $("#priority-note").hidden = anyHeatWave;
  $("#priority").innerHTML = state.districts.slice(0, 8).map((d, i) => rowButton(d.district,
    `<span class="rank">${i + 1}</span><span class="name">${esc(d.district)}</span>` +
    (d.imd_code !== "GREEN" ? chip(round(d.priority), d.imd_code)
      : `<span class="chip neutral" title="Priority ${round(d.priority)}/100 – no heat wave">${round(d.priority)}</span>`))).join("");
}

function renderDistrictSelect() {
  const select = $("#district-select");
  const names = [...state.byName.keys()].sort((a, b) => a.localeCompare(b));
  select.innerHTML = names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  if (state.selected) select.value = state.selected;
}

// ------------------------------------------------------------------ district detail
async function selectDistrict(name, { keepScroll = false } = {}) {
  const previous = state.selected;
  state.selected = name;
  if (previous && previous !== name) paintShape(previous);
  paintShape(name);
  $("#district-select").value = name;
  document.querySelectorAll(".row").forEach((row) => row.toggleAttribute("aria-current", row.dataset.district === name));

  const token = ++state.detailToken;
  const panel = $("#detail");
  if (!panel.querySelector(".hero")) panel.innerHTML = `<div class="skeleton" style="height:150px"></div><div class="skeleton" style="height:90px"></div>`;
  try {
    const d = await getJSON(withReplay(`/districts/${encodeURIComponent(name)}`));
    if (token !== state.detailToken) return;                   // a newer click won
    panel.innerHTML = detailHtml(d);
    if (!keepScroll && window.matchMedia("(max-width: 860px)").matches) panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    if (token === state.detailToken) panel.innerHTML = `<p class="muted">${esc(name)} – details are not available (${esc(error.message)}).</p>`;
  }
}

function feelsLikeText(d) {
  const sun = round(d.feels_like_now), shade = round(d.feels_like_shade_now);
  if ((d.solar_wm2 || 0) < 5) return `Feels like ${sun}° (sun is down)`;
  if (sun === shade) return `Feels like ${sun}°`;
  return `Feels like ${sun}° in the sun, ${shade}° in the shade`;
}

function friendlyReason(imd) {
  if (imd.code !== "GREEN") {
    const run = imd.longest_run;
    return `${imd.hw_days} heat-wave day${imd.hw_days === 1 ? "" : "s"} in the next 5 days, ${run} in a row.`;
  }
  if (imd.hw_days) return "One unusually hot day is coming. IMD only calls it a heat wave after two in a row.";
  return "Temperatures are within the usual range for this time of year.";
}

const kv = (label, value, tip = "") => `<div class="kv"${tip ? ` title="${esc(tip)}"` : ""}><span>${esc(label)}</span><span>${esc(value)}</span></div>`;

function detailHtml(d) {
  const [start, end, text] = temperatureGradient(d.feels_like_peak_today - 4);
  const pillBg = text === "#FFFFFF" ? "rgba(255,255,255,0.22)" : "rgba(15,23,42,0.10)";
  const wind = `${round(d.wind_ms * 3.6)} km/h`;
  const cloud = d.cloud_cover != null ? ` · Cloud ${round(d.cloud_cover)}%` : "";
  const today = d.forecast?.[0] || {};
  const when = today.peak_time ? `at ${today.peak_time}` : "in the sun";
  const hours = d.hours_in_danger_today;
  const imd = d.imd;

  const hero = `
    <section class="hero" style="background:linear-gradient(135deg, ${start}, ${end});color:${text}">
      <div class="hero-top"><h2>${esc(d.district)}</h2>
        <span class="pill" style="background:${pillBg}" title="How hot it gets for someone outdoors at the hottest time of today. ${esc(bandAdvice(d.heat_stress_band))}">Peak today: ${esc(bandLabel(d.heat_stress_band).toLowerCase())}</span></div>
      <div class="hero-main"><span class="temp">${round(d.temperature)}°C</span>
        <div><div class="feels">${feelsLikeText(d)}</div><div>Humidity ${round(d.humidity)}% · Wind ${wind}${cloud}</div></div></div>
      <div class="now" title="${esc(d.stress_model)} – how hot it feels to the body, counting sun, humidity, wind and heat from the ground (${esc(d.stress_category_now.toLowerCase())})">Now: ${esc(stressLabel(d.stress_category_now).toLowerCase())}</div>
    </section>`;

  const tiles = `
    <div class="tiles">
      <div class="tile" style="border-left-color:${tempColour(d.feels_like_peak_today - 4)}" title="UTCI 'feels like' temperature for someone standing in the sun">
        <h3>Hottest it'll feel today</h3><div class="value">${round(d.feels_like_peak_today)}°</div>
        <div class="sub">${esc(when)}${hours ? ` · ${hours} h of very strong heat` : ""}</div></div>
      <div class="tile" style="border-left-color:${bandColour(d.heat_stress_band)}" title="0–100. 70% how hot it feels today, 30% how many people are exposed">
        <h3>Risk today</h3><div class="value">${esc(bandLabel(d.heat_stress_band))}</div>
        <div class="sub">score ${round(d.relative_risk)}/100 · heat + people exposed</div></div>
    </div>
    <details class="more"><summary>More numbers</summary><div class="card">
      ${kv("Heat score", `${round(d.thermal_score)} / 100`, "75% the hottest it will feel, 25% the hours of very strong heat")}
      ${kv("Heat index now (shade)", `${round(d.heat_index_now)}°`, "Temperature with humidity, in the shade")}
      ${kv("Feels like now, in the shade", `${round(d.feels_like_shade_now)}°`)}
    </div></details>`;

  const chart = `<h3 class="section-title">Next 5 days</h3><div class="card">${chartSvg(d.forecast || [])}</div>`;

  const ens = d.ensemble || {};
  let status = `<div class="status-chips">${chip(CODE_NAMES[imd.code] || imd.code, imd.code)}` +
    (d.alert ? chip(titleCase(d.alert.level), d.alert.colour) : "") + `</div>` +
    `<p>${esc(d.alert ? `${d.alert.confidence}.` : friendlyReason(imd))}</p>` +
    kv("Heat-wave days (next 5)", `${imd.hw_days}${imd.severe_days ? `, ${imd.severe_days} severe` : ""}`);
  if (imd.hw_days) status += kv("Longest run", `${imd.longest_run} day${imd.longest_run === 1 ? "" : "s"}`);
  if (ens.total && (imd.code !== "GREEN" || ens.agree)) {
    status += kv("Other forecasts that agree", `${ens.agree} of ${ens.total}`) +
      `<p class="small muted">${Object.entries(ens.codes || {}).map(([k, v]) => `${esc(MODEL_NAMES[k] || k)}: ${esc((CODE_NAMES[v] || v).toLowerCase())}`).join(" · ")}</p>`;
  }
  status += kv("Hottest day this week", bandLabel(d.worst_band_5day));
  if (!d.normals_loaded) status += kv("Usual temperatures", "Not loaded – 45 °C rule only");
  const dot = bandColour(imd.code !== "GREEN" ? imd.code : d.worst_band_5day);
  status += `<hr><b>What to do</b><ul class="actions" style="--dot:${dot}">` +
    d.suggested_actions.map((a) => `<li>${esc(a)}</li>`).join("") + `</ul>`;
  const statusCard = `<section class="card" title="IMD heat-wave rules for ${esc(d.terrain)} districts"><h2>Heat-wave status</h2><div style="margin-top:10px">${status}</div></section>`;

  const days = `<section class="card days">${(d.forecast || []).map((day) => {
    const extra = [];
    if (day.hours_danger) extra.push(`${day.hours_danger} h of very strong heat`);
    if (day.departure != null) extra.push(`${day.departure >= 0 ? "+" : ""}${day.departure.toFixed(1)}° vs usual`);
    const hw = day.heatwave && day.heatwave !== "NONE"
      ? chip(day.heatwave.startsWith("SEVERE") ? "Severe heat wave" : "Heat wave", day.heatwave.startsWith("SEVERE") ? "RED" : "ORANGE") : "";
    return `<div class="day"><span class="d-name">${esc(day.date_text)}</span>
      <span class="d-temp">${round(day.temp_max)}° <small>/ ${round(day.temp_min)}°</small></span>
      <span class="d-feels">Feels ${round(day.stress)}°${day.peak_time ? ` at ${esc(day.peak_time)}` : ""}</span>
      <span class="d-chips">${hw}${chip(bandLabel(day.risk), day.risk)}</span>
      <span class="d-extra">${esc(extra.join(" · ") || "No hours of very strong heat")}</span></div>`;
  }).join("")}</section>`;

  const pop = d.population_2011;
  const people = `<section class="card"><h2>People</h2><div style="margin-top:10px">
    ${kv("Population (2011 census)", pop ? pop.toLocaleString("en-IN") : "Not available")}
    ${kv("Exposure score", d.vulnerability != null ? `${round(d.vulnerability)} / 100` : "State average")}
    ${d.response_capacity != null ? kv("Response capacity", `${round(d.response_capacity)} / 100`) : ""}
    <p class="small muted" style="margin-top:6px">${esc(d.census_note || "Census 2011 is still India's latest official count – Census 2027 figures will replace it.")}</p>
  </div></section>`;

  return hero + tiles + chart + statusCard + days + people;
}

function chartSvg(forecast) {
  if (!forecast.length) return `<p class="muted">No forecast.</p>`;
  const W = 440, H = 200, left = 34, right = 12, top = 26, bottom = 24;
  const temps = forecast.map((d) => d.temp_max), feels = forecast.map((d) => d.stress);
  const lo = 5 * Math.floor((Math.min(...temps, ...feels) - 2) / 5);
  const hi = 5 * (Math.floor((Math.max(...temps, ...feels) + 2) / 5) + 1);
  const n = forecast.length;
  const x = (i) => left + (W - left - right) * (n > 1 ? i / (n - 1) : 0.5);
  const y = (v) => H - bottom - ((v - lo) / (hi - lo)) * (H - top - bottom);
  const path = (vals) => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const text = "var(--text)", subtle = "var(--subtle)";
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Five-day forecast of feels-like and air temperature">`;
  for (let v = lo; v <= hi; v += 5) {
    svg += `<line x1="${left}" x2="${W - right}" y1="${y(v)}" y2="${y(v)}" stroke="var(--border)"/>` +
           `<text x="${left - 6}" y="${y(v) + 4}" text-anchor="end">${v}°</text>`;
  }
  forecast.forEach((d, i) => {
    const label = ["Today", "Tomorrow"].includes(d.date_text) ? d.date_text : d.date_text.split(" ")[0];
    const anchor = i === 0 ? "start" : i === n - 1 ? "end" : "middle";
    svg += `<text x="${x(i)}" y="${H - 6}" text-anchor="${anchor}">${esc(label)}</text>`;
  });
  svg += `<path d="${path(temps)}" fill="none" stroke="${subtle}" stroke-width="2.5" stroke-dasharray="7 5"/>` +
         `<path d="${path(feels)}" fill="none" stroke="${text}" stroke-width="3"/>`;
  forecast.forEach((d, i) => {
    svg += `<circle cx="${x(i)}" cy="${y(feels[i])}" r="6" fill="${bandColour(d.risk)}" stroke="var(--surface)" stroke-width="2">` +
           `<title>${esc(d.date_text)}: feels like ${round(d.stress)}°, air ${round(d.temp_max)}°</title></circle>`;
  });
  svg += `<line x1="${left}" x2="${left + 22}" y1="10" y2="10" stroke="${text}" stroke-width="3"/><text x="${left + 28}" y="14">Feels like (max)</text>` +
         `<line x1="${left + 150}" x2="${left + 172}" y1="10" y2="10" stroke="${subtle}" stroke-width="2.5" stroke-dasharray="7 5"/><text x="${left + 178}" y="14">Air temperature (max)</text>`;
  return svg + `</svg>`;
}

// ------------------------------------------------------------------ controls
function wireControls() {
  for (const id of ["#theme", "#login-theme"]) $(id).addEventListener("click", () => {
    const next = state.theme === "dark" ? "light" : "dark";
    applyTheme(next);
    storageSet("heat-theme", next);
  });
  $("#user-btn").addEventListener("click", () => toggleMenu());
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu")) toggleMenu(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggleMenu(false); });
  $("#sign-out").addEventListener("click", signOut);
  $("#open-log").addEventListener("click", () => { toggleMenu(false); openAlertLog(); });
  $("#log-close").addEventListener("click", () => $("#log-dialog").close());
  $("#log-rows").addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-i]");
    if (!row) return;
    $("#log-rows").querySelectorAll("tr").forEach((r) => r.setAttribute("aria-selected", String(r === row)));
    $("#log-message").textContent = `Message: ${state.logRows[row.dataset.i].message || "(none saved)"}`;
  });
  $("#log-rows").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.closest("tr[data-i]")?.click(); });
  wireLogin();
  document.querySelectorAll(".segmented button").forEach((button) => button.addEventListener("click", () => {
    state.layer = button.dataset.layer;
    document.querySelectorAll(".segmented button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    paintMap();
  }));
  $("#district-select").addEventListener("change", (e) => selectDistrict(e.target.value));
  document.addEventListener("click", (e) => {
    const target = e.target.closest(".row[data-district]");
    if (target) selectDistrict(target.dataset.district);
  });
  $("#source").addEventListener("change", (e) => { state.replay = e.target.value; loadData(); });
  $("#refresh").addEventListener("click", async () => {
    const button = $("#refresh");
    button.disabled = true;
    $("#updated").textContent = "Updating…";
    try {
      await getJSON("/refresh", { method: "POST" });
    } catch (error) {
      if (error.status !== 401) {           // 401: session ended, the sign-in page is already shown
        $("#error-banner").textContent = `Refresh failed: ${error.message}`;
        $("#error-banner").hidden = false;
      }
    }
    button.disabled = false;
    loadData({ quiet: true });
  });
  window.matchMedia("(min-width: 861px)").addEventListener("change", () => state.config && drawLegend());
}

// ------------------------------------------------------------------ sign in
function toggleMenu(open) {
  const panel = $("#user-menu");
  const show = open ?? panel.hidden;
  panel.hidden = !show;
  $("#user-btn").setAttribute("aria-expanded", String(show));
  if (show) {                              // open towards whichever side has room
    panel.style.left = panel.style.right = "";
    if (panel.getBoundingClientRect().left < 8) { panel.style.left = "0"; panel.style.right = "auto"; }
  }
}

function showLogin(notice = "") {
  clearInterval(state.pollTimer);
  state.user = null;
  $("#app").hidden = true;
  $("#login").hidden = false;
  $("#login-notice").textContent = notice;
  $("#login-notice").hidden = !notice;
  $("#login-pass").value = "";
  $(storageGet("heat-login-user") ? "#login-pass" : "#login-user").focus();
}

function sessionEnded() {
  if (state.user) showLogin("Your session has ended – please sign in again.");
}

function wireLogin() {
  const savedRole = storageGet("heat-login-role");
  if (savedRole) $("#login-role").value = savedRole;
  $("#login-user").value = storageGet("heat-login-user") || "";
  $("#login-eye").addEventListener("click", () => {
    const field = $("#login-pass");
    const show = field.type === "password";
    field.type = show ? "text" : "password";
    $("#login-eye").textContent = show ? "Hide" : "Show";
    $("#login-eye").setAttribute("aria-pressed", String(show));
    $("#login-eye").setAttribute("aria-label", show ? "Hide password" : "Show password");
  });
  const caps = (e) => { if (e.getModifierState) $("#login-caps").hidden = !e.getModifierState("CapsLock"); };
  $("#login-pass").addEventListener("keydown", caps);
  $("#login-pass").addEventListener("keyup", caps);
  $("#login-pass").addEventListener("blur", () => { $("#login-caps").hidden = true; });
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const error = $("#login-error");
    const username = $("#login-user").value.trim(), password = $("#login-pass").value;
    if (!username || !password) {
      error.textContent = "Please enter both your login ID and password.";
      error.hidden = false;
      return;
    }
    const button = $("#login-submit");
    button.disabled = true;
    button.textContent = "Signing in…";
    error.hidden = true;
    try {
      const user = await getJSON("/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, role: $("#login-role").value }),
      });
      $("#login-pass").value = "";         // don't keep the password in the page
      storageSet("heat-login-user", username);
      storageSet("heat-login-role", $("#login-role").value);
      startDashboard(user);
    } catch (err) {
      error.textContent = err.status === 422 ? "Please check the login ID and password." : err.message;
      error.hidden = false;
      $("#login-pass").select();
    } finally {
      button.disabled = false;
      button.textContent = "Sign in";
    }
  });
}

// ------------------------------------------------------------------ alert log (System Admin)
function logTime(stamp) {
  const when = new Date(stamp);
  return isNaN(when) ? stamp || "" : when.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

async function openAlertLog() {
  const channels = state.config.alert_gateway || [];
  $("#log-sub").textContent = channels.length ? `Alerts go out by ${channels.join(" and ")}.`
    : "Text messages aren't set up yet, so alerts are saved here instead of being sent.";
  $("#log-rows").innerHTML = `<tr><td colspan="7" class="muted">Loading…</td></tr>`;
  $("#log-message").textContent = "";
  $("#log-dialog").showModal();
  try {
    state.logRows = await getJSON("/alerts/log?limit=200");
  } catch (error) {
    if (error.status === 401) { $("#log-dialog").close(); return; }
    $("#log-rows").innerHTML = `<tr><td colspan="7">Could not load the log: ${esc(error.message)}</td></tr>`;
    return;
  }
  const rows = state.logRows;
  $("#log-rows").innerHTML = rows.length ? rows.map((r, i) => `<tr data-i="${i}" tabindex="0">
      <td>${esc(logTime(r.timestamp))}</td><td>${esc(r.district)}</td><td>${esc(titleCase(r.level))}</td>
      <td>${r.code ? chip(titleCase(r.code), r.code) : ""}</td><td>${esc(r.heat_from)}</td>
      <td>${esc(r.recipient)}</td><td>${esc(r.status)}</td></tr>`).join("")
    : `<tr><td colspan="7" class="muted">No alerts yet – nothing has been confirmed as a warning.</td></tr>`;
  $("#log-message").textContent = rows.length ? "Click a row to see the message that was sent." : "";
}

async function signOut() {
  toggleMenu(false);
  try { await getJSON("/auth/logout", { method: "POST" }); } catch { /* already signed out */ }
  showLogin();
}

async function startDashboard(user) {
  state.user = user;
  const role = user.role === "admin" ? "System Admin" : "City Administrator";
  const where = user.district || user.city || state.config.state;
  $("#user-name").textContent = user.full_name || user.username;
  $("#user-full").textContent = user.full_name || user.username;
  $("#user-role").textContent = `${role} • ${where}`;
  $("#open-log").hidden = user.role !== "admin";          // officer names: System Admin only
  $("#login").hidden = true;
  $("#app").hidden = false;
  if (!state.mapBuilt) {
    state.mapBuilt = true;
    drawLegend();
    await buildMap();
  } else {
    state.map.invalidateSize();
    fitMap();
  }
  state.selected = null;                   // start on this user's own district
  await loadData();
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(() => { if (!state.replay) loadData({ quiet: true }); }, LIVE_POLL_MS);
}

async function start() {
  const saved = storageGet("heat-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  wireControls();
  try {
    state.config = await getJSON("/ui/config");
  } catch (error) {
    showLogin(`Can't reach the Heat Intelligence server (${error.message}). Start it with: python api.py`);
    $("#login-submit").disabled = true;
    return;
  }
  applyTheme(saved === "dark" || saved === "light" ? saved : prefersDark ? "dark" : "light");
  document.title = `Heat Intelligence • ${state.config.state}`;
  $(".map-title").textContent = `${state.config.state} • Heat Risk Map`;
  const channels = state.config.alert_gateway || [];
  $("#about-alerts").textContent = channels.length ? `Alerts by ${channels.join(" and ")}` : "Text alerts not set up – saved to the log";
  try {
    for (const r of await getJSON("/replays")) $("#source").add(new Option(`Replay: ${r.label}`, r.start));
  } catch { /* replays are optional */ }
  try {
    startDashboard(await getJSON("/auth/me"));
  } catch {
    showLogin();
  }
}

start();
