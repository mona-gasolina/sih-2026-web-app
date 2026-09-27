# Heat Intelligence — Tamil Nadu Prototype

A modular PyQt5 prototype for SIH 2026 Problem Statement 26083:
**Extreme Heatwave Early Warning and Human Thermal Stress Index**.

## Features

- Professional role-based login screen.
- `System Admin` can create assigned `City Administrator` accounts.
- City administrators can log into the authority dashboard.
- Public user access is shown as a future/disabled role.
- Tamil Nadu district polygons remain the prototype GIS layer.
- Hovering a district shows a small cursor-adjacent card with:
  - Relative risk score
  - Thermal score
  - Census population exposure
  - Temperature
  - Humidity
- Clicking a district opens its full detail panel on the right.
- Selecting the district from the left dropdown does the same thing without hiding the selector.
- Clicking a district collapses the left controls panel.
- Right panel contains current metrics and a 5-day thermal outlook.
- Live weather uses Open-Meteo without an API key.
- **Replay mode** (left panel → WEATHER DATA): archived weather for the real
  30 Apr – 4 May 2024 Tamil Nadu heat wave, so the warning flow can be shown
  outside the heat season. Clearly labelled; nothing is sent to officers.
- `pythermalcomfort` is used for UTCI/thermal-stress calculations.
- Census 2011 district population data is bundled as a prototype demographic layer.
- The code is structured so district polygons can later be replaced by ward/zone/locality GeoJSON.

## What the prototype does (mapped to the idea submission)

| Idea submission | Where it is in the app |
|---|---|
| Human Thermal Stress Index from temperature, humidity, wind, radiation | `thermal.py` – UTCI via pythermalcomfort, hour by hour; radiation from direct sun, diffuse light, clouds and ground heat (ERA5-HEAT method) |
| Rule-based risk classifier + 3–5 day forecaster | `heatwave.py` – IMD heat-wave criteria, YELLOW / ORANGE / RED; `thermal.py` – UTCI stress bands VERY LOW → EXTREME |
| Heat exposure duration modelling | Hours per day in the danger range count towards the thermal score |
| Relative risk score with demographic vulnerability | 70 % thermal score + 30 % Census 2011 population exposure |
| GIS dashboard with drill-down and forecast trends | Map, hover card, right panel, 5-day trend chart |
| Persistent / confidence-based alerting | `alerts.py` – IMD YELLOW+ heat wave: WATCH after 1 update; WARNING after 2 updates ≥ 6 h apart **and** at least one independent model (ECMWF / GFS / ICON) agreeing; no repeat message within 48 h unless it gets worse |
| SMS / WhatsApp alerts to city administration | `alerts.py` – Twilio REST (set env vars), otherwise logged to `data/alert_log.csv` |
| Preparedness-based prioritisation | "Priority districts" list; add `data/response_capacity.csv` for capacity |
| Actionable decision support | Suggested actions per district |
| Cache weather, refresh hourly; avoid API overload | One batched Open-Meteo request for all districts, cached 60 min |
| Demonstrable outside summer | Replay of the 30 Apr – 4 May 2024 heat wave (`weather.get_replay_weather`) |

### Thermal engine note (Python 3.14)

`pythermalcomfort` needs `numba`, which may not install on very new Python
versions. If it can't load, the app uses the NOAA/NWS **heat index** as a
fallback (clearly labelled in the UI and status bar). For UTCI, use Python 3.12
or 3.13:

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

### Scoring (prototype – documented so it can be reviewed)

Each index is mapped to 0–100 using its own published category boundaries:

| Score | 25 | 50 | 75 | 95 |
|---|---|---|---|---|
| UTCI (°C) | 26 moderate | 32 strong | 38 very strong | 46 extreme |
| Heat index (°C) | 26.7 caution | 32.2 extreme caution | 39.4 danger | 51.7 extreme danger |

Thermal score = 75 % peak score + 25 % duration score (hours at the "75" level; 6 h = 100).
Bands follow the UTCI categories of the same heat, so the label never
contradicts the "feels like": < 25 VERY LOW (no stress), < 50 LOW (moderate),
< 75 MODERATE (strong), < 92 HIGH (very strong), ≥ 92 EXTREME (extreme, or very
strong heat for most of the day). A typical hot Tamil Nadu afternoon is HIGH;
EXTREME is kept for days that stand out, to avoid "heat fatigue".

### How "feels like" handles sun, cloud and ground heat

UTCI needs the **mean radiant temperature** (MRT) – how much heat reaches the
body as radiation. It is computed every hour from the forecast, following the
method behind the Copernicus ERA5-HEAT data set (Di Napoli et al. 2020,
*Int J Biometeorol* 64:1233):

- direct sun (direct normal irradiance) × the body's projected area at the real
  sun elevation for that district and hour,
- diffuse sky light and sunlight reflected off the ground (albedo 0.2),
- longwave heat from the sky (Brutsaert clear-sky emissivity, raised by cloud
  cover as in Crawford & Duchon 1999) and from the ground (forecast ground
  surface temperature – often 50 °C on a sunny afternoon).

So clouds count twice: they cut direct sun, and they add heat at night and on
humid days. The earlier indoor-comfort formula (ASHRAE 55 solar gain) assumed a
clear sky and a fixed sun angle, and overstated afternoon "feels like" by about
2–3 °C.

### Avoiding warning fatigue

1. Warnings use IMD heat-wave rules (temperature vs the local normal), not the
   UTCI band – ordinary summer days are hot but not heat waves.
2. A heat wave must show up in two forecast updates at least 6 h apart.
3. At least one of three independent models (ECMWF, GFS, ICON, each corrected
   for running warm or cool, `data/model_bias.json`) must agree with the main
   forecast. Requiring 2 of 3 was tested and rejected: on the May 2024 replay it
   would have missed Erode, where the coarser models under-forecast the heat.
4. Once sent, a district is not messaged again within 48 h unless the colour
   gets worse (e.g. ORANGE → RED is sent as an update).

On the May 2024 replay this gives 19 warnings and holds back 4 low-confidence
districts (e.g. Krishnagiri, where no other model agreed).

### Heat-wave warnings (IMD criteria)

UTCI measures how stressful the heat is for a person in the sun, but on its own
it can't tell a normal summer day from a heat wave: an ordinary May afternoon
in Madurai already counts as "extreme heat stress". Warnings therefore follow
the IMD heat-wave definition (`heatwave.py`):

| Terrain | Heat wave considered from | Heat wave | Severe heat wave |
|---|---|---|---|
| Plains | Tmax ≥ 40 °C | +4.5 to +6.4 °C above normal | more than +6.4 °C |
| Coastal districts | Tmax ≥ 37 °C | same | same |
| Hills (Nilgiris) | Tmax ≥ 30 °C | same | same |
| Any | – | Tmax ≥ 45 °C | Tmax ≥ 47 °C |

District colour over the 5-day forecast: **YELLOW** = heat wave on 2 days in a row,
**ORANGE** = severe heat wave on 2 days in a row or heat wave on 4+ days in a row,
**RED** = severe heat wave on 3+ days in a row. Only YELLOW or above raises a
WATCH/WARNING. A WARNING needs the heat wave in two forecast updates at least
6 h apart: the app downloads hourly, but the models behind Open-Meteo publish a
new run about every 6 h, so two downloads an hour apart are usually the same
forecast. UTCI is still shown and used to rank districts and choose the
day-to-day advice. The peak UTCI assumes a person in full sun, and a shade value
is shown next to it.

Normal daily maximum temperatures (`data/tmax_normals.json`) are built once from
Open-Meteo's archive of past forecasts (2022–2025, smoothed ±15 days). That's the
same model family as the live forecast, so model bias doesn't distort the
departures. The model reads about 1–3 °C cooler than IMD station normals in
summer, so the absolute 40/37 °C thresholds are slightly conservative. Delete
the file to rebuild it. If it can't be loaded, only the 45/47 °C rule applies,
and the status bar says so.

### Checked against a real event

Run on archived weather for 30 Apr – 4 May 2024, these rules flag 23 of 37
districts (Madurai, Theni, Krishnagiri RED; Erode, Vellore, Tiruchirappalli,
Thiruvallur and others ORANGE), matching the heat-wave warnings IMD issued for
interior Tamil Nadu at the time. Madurai: Tmax 41.8 → 43.7 °C, +5 to +7 °C
above normal. The same scan finds almost nothing in 2025. This is the replay
event in the app.

### Cold

UTCI covers cold stress too, so cold Nilgiris nights are labelled with the
UTCI cold categories. Cold-wave *warnings* are not part of this prototype: the
problem statement is about heat, and Tamil Nadu has no IMD cold-wave regime
outside the Nilgiris. They are listed under future scope.

### Optional data files

- `data/response_capacity.csv` – columns `district,capacity_index` (0–100). Used in prioritisation.

### SMS / WhatsApp alerts

Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_FROM` (SMS) and/or
`TWILIO_WHATSAPP_FROM`. Alerts go to active city administrators assigned to the
district who have a mobile number. Without these variables everything is logged only.

## Accessibility & UI

- Light and dark mode (top bar and sign-in screen), remembered per computer.
- Text size 100–160 % (A− / A+, `Ctrl +`, `Ctrl −`, `Ctrl 0`), remembered per computer.
- All text colours meet WCAG AA contrast (4.5:1), including on gradient cards.
- Follows Windows display scaling exactly (125 %, 150 %, 175 %) instead of Qt 5's rounding
  (which turned 150 % into 200 % and made the app too big for smaller laptops).
- The dashboard adapts to the window: below 1600 px (logical) the top bar and right panel
  get slimmer; below 1400 px the side panel starts collapsed (☰ opens it). Below its
  minimum size it scrolls instead of clipping. Dialogs never open larger than the screen.
- Password fields have a show/hide eye; Caps Lock warning; 5 failed sign-ins → 60 s lock.

## Run

```bash
python -m pip install -r requirements.txt
python main.py
```

On first launch, the app downloads the Tamil Nadu GeoJSON if it is not already present.

### Web API (FastAPI)

```bash
python api.py
```

Then open http://127.0.0.1:8000/docs for the interactive API documentation.
The API serves the same numbers as the desktop app as JSON (`/districts`,
`/districts/{name}`, `/alerts`, `/geojson`, …), recomputes every hour with
APScheduler and sends confirmed warnings via Twilio, as in the idea submission.
Add `?replay=2024-04-30` to see the 2024 heat wave. Set `HEAT_API_KEY` to protect
`/alerts/log` and `/refresh`. Details: CODEBASE_GUIDE §8b.

### Prototype admin login

- Access type: System Admin
- Login ID: `admin`
- Password: `Admin@123`

After logging in as System Admin, use **Manage Access** to create City Administrator accounts.

## Project structure

- `main.py` — application integration, UI wiring, weather workers
- `config.py` — theme and configuration
- `auth.py` — prototype local role-based authentication
- `login.py` — login and account creation UI
- `map_view.py` — GIS map, hover card and click handling
- `panels.py` — detail panel, metrics and forecast cards
- `thermal.py` — UTCI / heat index, duration-aware thermal score, relative risk
- `heatwave.py` — IMD heat-wave criteria and the YELLOW / ORANGE / RED district code
- `pipeline.py` — turns weather + Census into per-district metrics (runs in background thread)
- `alerts.py` — persistent alerting, suggested actions, SMS/WhatsApp dispatch, alert log
- `service.py` — one recompute for all districts, shared by the app and the API
- `api.py` — FastAPI web API with hourly APScheduler job
- `ui_controls.py` — text size, light/dark toggle, password eye field
- `weather.py` — batched hourly Open-Meteo requests with 1-hour cache, Tmax normals, replay
- `data_manager.py` — GeoJSON and Census data loading
- `data/census_tn_2011.csv` — district-level Census 2011 prototype data
- `data/tmax_normals.json` — daily Tmax normals per district (built once, bundled)
- `data/replay_2024-04-30.json` — archived weather for the replay (created on first use; commit it for offline demos)
- `data/users.json` — generated local prototype accounts (not committed)

## Important prototype limitation

The SIH concept calls for **ward/zone-level or hyperlocal** risk mapping. The current map is intentionally district-level because the current GeoJSON is a district map.

The data model is already separated from the geometry. To move to hyperlocal mode later:

1. Replace `data/tamil_nadu.geojson` with ward/zone GeoJSON.
2. Add a ward/zone Census 2011 table.
3. Add finer weather/downscaled data.
4. Add green-cover, road, building/land-surface and other exposure layers.
5. Replace the population-only vulnerability proxy with validated heat-mortality relationships
   (Census 2011 age 60+ share and agricultural/outdoor-worker share are the obvious first additions).

Other known gaps: the map has 37 districts (Mayiladuthurai, formed 2020, is inside Nagapattinam),
and districts formed after 2011 have no Census 2011 population of their own.

## Future scope

- **Other states.** Only `STATE_NAME`, the GeoJSON, the Census CSV and the `COASTAL` / `HILLS`
  sets in `heatwave.py` are Tamil Nadu-specific; normals are rebuilt automatically for new areas.
  A state selector would load these per state.
- **Cold waves** for northern states (IMD cold-wave criteria on Tmin), reusing the same
  persistence and alert flow.
- **Web dashboard** on the stack in the idea submission: the FastAPI backend (`api.py`)
  exists; next are a React + Leaflet frontend on top of it and PostgreSQL/PostGIS in
  place of the local JSON/CSV files.

## Data sources and rationale

The project PDF specifies:
- PostgreSQL/PostGIS or GeoJSON + spatial processing
- FastAPI
- pandas
- pythermalcomfort
- APScheduler
- Twilio
- React + Leaflet/Mapbox
- Census and weather API data
- NFHS/government health data
- ward-level GIS mapping

This prototype implements the backend part of that stack (FastAPI, pythermalcomfort,
APScheduler, Twilio, GeoJSON) and uses a PyQt desktop
dashboard in place of the React/Leaflet frontend. Local files stand in for PostgreSQL.

### Weather data – what Open-Meteo is

[Open-Meteo](https://open-meteo.com) is a free weather API that serves the
forecasts national weather services publish – ECMWF (Europe), GFS (USA), ICON
(Germany) and others – without an API key. Used here:

| What | Open-Meteo API | Used for |
|---|---|---|
| Hourly forecast, 5 days: temperature, humidity, wind, global / direct / diffuse radiation, cloud cover, ground surface temperature | Forecast API | UTCI, heat index, danger hours |
| Daily max temperature from ECMWF, GFS and ICON separately | Forecast API (`models=`) | Second-opinion check before warnings |
| Daily max temperature 2022–2025 | Historical forecast API | Usual (normal) Tmax per district and date |
| Same, per model, since Feb 2024 | Historical forecast API | Each model's warm/cool bias |
| Hourly weather for 30 Apr – 4 May 2024 | Historical forecast API | Replay |

Limitations: one grid point per district (≈ 9–25 km models), and normals from 4
years of model data rather than IMD's 30-year station normals.

### Other data sources worth adding

| Source | What it gives | Use |
|---|---|---|
| IMD (mausam.imd.gov.in) – district heat-wave warnings, station observations and normals | Official warnings and 30-year normals | Validate our warnings; replace model normals |
| NDMA SACHET (sachet.ndma.gov.in) – CAP alert feed | Official alerts already issued | Avoid duplicating / contradicting official alerts |
| Copernicus ERA5-HEAT (Climate Data Store) | Hourly UTCI and MRT reanalysis since 1940 | Check our UTCI against the reference data set |
| Census 2011 tables C-13 (age) and B-series (workers) | Share of people 60+ and of agricultural / marginal workers per district | Real vulnerability instead of population only |
| NFHS-5 district fact sheets | Health indicators (e.g. hypertension, anaemia) | Health vulnerability |
| Tamil Nadu SDMA Heat Action Plan | Official actions per alert level | Replace the prototype action text |
| ESA WorldCover / Bhuvan land use; OpenStreetMap | Green cover, built-up area, hospitals, cooling points | Ward-level heat exposure and response capacity |

### Census source

The bundled population data is based on Census 2011 district population figures. The production demographic layer should use the official Census tables at ward/sub-district/town/village level where available.

## Colour system

Themes live in `config.py` (`THEMES["light"]`, `THEMES["dark"]`); stylesheets use `$tokens`.
Heat scale (map, legend, cards): blue → cyan → green → yellow → orange → red → deep red.

## Security warning

The local JSON authentication is only for a prototype. For deployment, move accounts to FastAPI/PostgreSQL, hash passwords using a production authentication library, use HTTPS, sessions/JWT, audit logs, account deactivation and proper role/permission enforcement.
