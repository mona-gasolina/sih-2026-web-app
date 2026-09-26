# Heat Intelligence — Tamil Nadu Prototype

A modular PyQt5 prototype for SIH 2026 Problem Statement 26083:
**Extreme Heatwave Early Warning and Human Thermal Stress Index**.

## What changed

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
- `pythermalcomfort` is used for UTCI/thermal-stress calculations.
- Census 2011 district population data is bundled as a prototype demographic layer.
- The code is structured so district polygons can later be replaced by ward/zone/locality GeoJSON.

## What the prototype does (mapped to the idea submission)

| Idea submission | Where it is in the app |
|---|---|
| Human Thermal Stress Index from temperature, humidity, wind, radiation | `thermal.py` – UTCI via pythermalcomfort, hour by hour |
| Rule-based risk classifier + 3–5 day forecaster | `heatwave.py` – IMD heat-wave criteria, YELLOW / ORANGE / RED; `thermal.py` – UTCI stress bands VERY LOW → EXTREME |
| Heat exposure duration modelling | Hours per day in the danger range count towards the thermal score |
| Relative risk score with demographic vulnerability | 70 % thermal score + 30 % Census 2011 population exposure |
| GIS dashboard with drill-down and forecast trends | Map, hover card, right panel, 5-day trend chart |
| Persistent / confidence-based alerting | `alerts.py` – IMD YELLOW+ heat wave: WATCH after 1 update, WARNING after 2 consecutive updates |
| SMS / WhatsApp alerts to city administration | `alerts.py` – Twilio REST (set env vars), otherwise logged to `data/alert_log.csv` |
| Preparedness-based prioritisation | "Priority districts" list; add `data/response_capacity.csv` for capacity |
| Actionable decision support | Suggested actions per district |
| Cache weather, refresh hourly; avoid API overload | One batched Open-Meteo request for all districts, cached 60 min |

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
Bands: < 25 VERY LOW, < 45 LOW, < 60 MODERATE, < 75 HIGH, ≥ 75 EXTREME.

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
WATCH/WARNING. UTCI is still shown and used to rank districts and choose the
day-to-day advice. The peak UTCI assumes a person in full sun, and a shade value
is shown next to it.

Normal daily maximum temperatures (`data/tmax_normals.json`) are built once from
Open-Meteo's archive of past forecasts (2022–2025, smoothed ±15 days). That's the
same model family as the live forecast, so model bias doesn't distort the
departures. The model reads about 1–3 °C cooler than IMD station normals in
summer, so the absolute 40/37 °C thresholds are slightly conservative. Delete
the file to rebuild it. If it can't be loaded, only the 45/47 °C rule applies,
and the status bar says so.

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
- The dashboard is laid out at maximised size; a smaller window scrolls instead of shrinking.
- Password fields have a show/hide eye; Caps Lock warning; 5 failed sign-ins → 60 s lock.

## Run

```bash
python -m pip install -r requirements.txt
python main.py
```

On first launch, the app downloads the Tamil Nadu GeoJSON if it is not already present.

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
- `pipeline.py` — turns weather + Census into per-district metrics (runs in background thread)
- `alerts.py` — persistent alerting, SMS/WhatsApp dispatch, alert log
- `ui_controls.py` — text size, light/dark toggle, password eye field
- `weather.py` — batched hourly Open-Meteo requests with 1-hour cache
- `data_manager.py` — GeoJSON and Census data loading
- `data/census_tn_2011.csv` — district-level Census 2011 prototype data
- `data/users.json` — generated local prototype accounts

## Important prototype limitation

The SIH concept calls for **ward/zone-level or hyperlocal** risk mapping. The current map is intentionally district-level because the current GeoJSON is a district map.

The data model is already separated from the geometry. To move to hyperlocal mode later:

1. Replace `data/tamil_nadu.geojson` with ward/zone GeoJSON.
2. Add a ward/zone Census 2011 table.
3. Add finer weather/downscaled data.
4. Add green-cover, road, building/land-surface and other exposure layers.
5. Replace the population-only vulnerability proxy with validated heat-mortality relationships.
6. Add confidence/persistence logic before automated alerts.

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

This PyQt prototype keeps the same conceptual modules while using local files so the prototype can run without a full backend.

### Free weather source

Open-Meteo is used for the prototype because it provides forecast data without an API key. For a production system, the weather provider should be selected according to the project's data licensing, accuracy and operational requirements.

### Census source

The bundled population data is based on Census 2011 district population figures. The production demographic layer should use the official Census tables at ward/sub-district/town/village level where available.

## Colour system

Themes live in `config.py` (`THEMES["light"]`, `THEMES["dark"]`); stylesheets use `$tokens`.
Heat scale (map, legend, cards): blue → cyan → green → yellow → orange → red → deep red.

## Security warning

The local JSON authentication is only for a prototype. For deployment, move accounts to FastAPI/PostgreSQL, hash passwords using a production authentication library, use HTTPS, sessions/JWT, audit logs, account deactivation and proper role/permission enforcement.
