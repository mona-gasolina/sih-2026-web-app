# Heat Intelligence – Codebase Guide

A plain-language tour of the code for anyone who knows basic Python
(variables, functions, `if`/`for`, dictionaries, `import`).
You do **not** need to know PyQt to follow this guide.

---

## 1. What the app does, in one paragraph

The app downloads a weather forecast for every district in Tamil Nadu and
works out how hot it **feels** to a human body, not just the air
temperature. It turns that into a risk score, colours a map, and shows
the details for each district. When a district stays high-risk across
forecast updates, it warns the officer in charge of that district.

---

## 2. How to run it

```bash
python -m pip install -r requirements.txt
python main.py
```

Prototype sign-in: **Access type** = System Admin, **Login ID** = `admin`, **Password** = `Admin@123`.

> Use `python -m pip`, not plain `pip`. It installs into the same Python
> that `python` runs. If `pythermalcomfort` won't install on your Python
> version, use Python 3.12 or 3.13 (see the README).

---

## 3. The files at a glance

Think of the app as layers. Each layer only uses the ones below it.

```
 ┌──────────────────────────────────────────────────────────────┐
 │  SCREENS (what you see)                                      │
 │  main.py  login.py  panels.py  map_view.py  ui_controls.py   │
 ├──────────────────────────────────────────────────────────────┤
 │  LOGIC (the maths and rules – no windows or buttons)         │
 │  pipeline.py  thermal.py  alerts.py  auth.py                 │
 ├──────────────────────────────────────────────────────────────┤
 │  DATA (getting and saving information)                       │
 │  weather.py  data_manager.py                                 │
 ├──────────────────────────────────────────────────────────────┤
 │  SETTINGS (colours, sizes, file paths)                       │
 │  config.py                                                   │
 └──────────────────────────────────────────────────────────────┘
```

| File | In one sentence |
|---|---|
| `main.py` | Starts the app, builds the main dashboard window and wires everything together. |
| `login.py` | The sign-in screen, the "create account" form and the "Manage Access" screen. |
| `panels.py` | The right-hand panel: district banner, number cards, 5-day chart, forecast rows. |
| `map_view.py` | Draws the Tamil Nadu map, colours each district, shows the hover card. |
| `ui_controls.py` | Small reusable pieces: text-size buttons, light/dark switch, password field with the eye. |
| `pipeline.py` | Takes raw weather and population for one district and produces every number the screen shows. |
| `thermal.py` | The science: "feels like" temperature, scores (0–100) and risk bands. |
| `heatwave.py` | IMD heat-wave criteria: is a day a heat wave, and the district's YELLOW/ORANGE/RED code. |
| `alerts.py` | Decides when to raise an alert, what action to suggest, and sends SMS/WhatsApp (or logs it). |
| `service.py` | One full recompute for all districts; used by both the desktop app and the API. |
| `api.py` | The web API (FastAPI): the same numbers as JSON, hourly recompute with APScheduler. |
| `auth.py` | User accounts: sign-in, password hashing, lockout, creating/deactivating officers. |
| `weather.py` | Downloads the forecast from Open-Meteo and caches it for an hour; Tmax normals; replay of a past heat wave. |
| `data_manager.py` | Reads the map file and the Census population file. |
| `config.py` | All settings in one place: colours, themes, font sizes, file paths. |
| `s1.py`, `s2.py` | Older experiments. Not used by the app. |

### The `data/` folder

| File | What it is | Committed to git? |
|---|---|---|
| `tamil_nadu.geojson` | District shapes (the map outlines) | Yes |
| `census_tn_2011.csv` | Population per district (Census 2011) | Yes |
| `users.json` | Accounts (passwords stored as hashes, never plain text) | No |
| `ui_settings.json` | This computer's text size and light/dark choice | No |
| `weather_cache.json` | Last downloaded forecast (reused for 1 hour) | No |
| `alert_state.json` | How many updates in a row each district has been risky | No |
| `alert_log.csv` | Every alert that was sent or logged | No |
| `tmax_normals.json` | Normal daily max temperature per district (for IMD departures) | Yes |
| `replay_2024-04-30.json` | Archived weather for the replay mode (made on first use) | Yes, for offline demos |
| `response_capacity.csv` | *Optional.* Preparedness score per district (0–100) | Yes, if you add it |

---

## 4. What happens when you run `python main.py`

Follow this top to bottom, and you'll know how the whole app flows.

```
main()                                   main.py
 │
 ├─ load_ui_settings()                   config.py   → remembers text size + theme
 ├─ AuthManager()                        auth.py     → creates users.json with "admin" if missing
 ├─ LoginDialog(...).exec_()             login.py    → waits until someone signs in
 │
 └─ MainWindow(user)                     main.py
      ├─ build_ui()                      → top bar, left panel, map, right panel, status bar
      ├─ prepare_locations()             → list of (district, latitude, longitude)
      └─ load_weather()                  → starts WeatherWorker in the background
               │
               ▼   (runs on a separate thread so the window doesn't freeze)
         WeatherWorker.run()  →  compute_all(...)   service.py (shared with the web API)
           ├─ get_weather(...)            weather.py   → one request for ALL districts (or cache)
           └─ compute_zone(...) per district  pipeline.py → uses thermal.py for the maths
               │
               ▼   (results come back to the main window)
         MainWindow.weather_ready(results, info)
           ├─ map.update_zone(...)        → recolours each district
           ├─ alerts.evaluate(...)        → WATCH / WARNING list
           ├─ alerts.dispatch(...)        → notifies officers for new WARNINGs
           └─ updates summary tiles, alert list, priority list, right panel
```

A timer calls `load_weather()` again every hour, and **F5** or the
"Refresh live weather" button calls it immediately.

**Replay mode.** Choosing a replay under WEATHER DATA sets `MainWindow.replay`
to a start date. The same worker then calls `get_weather(..., replay=date)`,
which returns archived weather for those 5 days, and `compute_zone(..., replay=date)`
uses that date as "today". Alerts are shown but never sent or stored.

---

## 5. The science, step by step (`thermal.py`)

### 5.1 "Feels like" temperature

Air temperature alone doesn't tell you how dangerous heat is. Humidity,
wind and sunshine matter too.

- **UTCI** (Universal Thermal Climate Index) uses all four: temperature,
  humidity, wind and solar radiation. It comes from the `pythermalcomfort`
  library.
- **Heat index** (NOAA/NWS) uses temperature and humidity only. It's the
  **fallback** when `pythermalcomfort` isn't installed.

```python
value, model = stress_value(tdb=35, rh=60, wind=2.0, solar=700)
# value = e.g. 41.3,  model = "UTCI" or "Heat index"
```

### 5.2 Turning it into a 0–100 score

Each index has official categories. We pin those category boundaries to
fixed scores and draw straight lines in between:

| Score → | 25 | 50 | 75 | 95 |
|---|---|---|---|---|
| UTCI °C | 26 (moderate) | 32 (strong) | 38 (very strong) | 46 (extreme) |
| Heat index °C | 26.7 (caution) | 32.2 (extreme caution) | 39.4 (danger) | 51.7 (extreme danger) |

So a heat index of 35.8°C (halfway between 32.2 and 39.4) scores 62.5.
That's `score_from_stress()`.

### 5.3 How long the heat lasts

A one-hour spike is less dangerous than six hours of heat. For each day
we count the **hours in the danger range** (heat index ≥ 39.4°C or
UTCI ≥ 38°C). 6 hours or more = 100.

```
thermal score = 75% × peak score  +  25% × duration score
```

That's `combined_thermal_score()`. The card that says
**"0 h in danger range today"** is this hour count.

### 5.4 Risk band

| Thermal score | Band |
|---|---|
| under 25 | VERY LOW |
| 25 – 44 | LOW |
| 45 – 59 | MODERATE |
| 60 – 74 | HIGH |
| 75 and above | EXTREME |

### 5.5 Relative risk (heat + people)

```
relative risk = 70% × thermal score  +  30% × population exposure score
```

The population part (`vulnerability_score()`) is bigger for districts
with more people. It's a placeholder until elderly, outdoor-worker and
health data are added.

> These weights and cut-offs are **prototype choices** written down so
> the team can review them. They aren't from a published model.

---

## 6. From weather to screen numbers (`pipeline.py`)

`compute_zone(data, demographic, capacity)` is the main function. For
**one** district it:

1. Groups the hourly forecast into days (up to 5).
2. Calls `summarise_day()` for each day → peak feels-like, danger hours, score, band.
3. Works out "right now" values with `calculate_current()`.
4. Adds the population-based relative risk.
5. Counts high-risk days and the longest run of them in a row.
6. Computes a **priority score** for the "Priority districts" list:
   `60% risk (next 3 days) + 25% danger hours + 15% (100 − response capacity)`.

It returns one big dictionary. Every screen reads from that dictionary.
The keys you'll see most often:

| Key | Meaning |
|---|---|
| `temperature`, `humidity`, `wind` | Current conditions (wind in m/s) |
| `stress`, `stress_model` | Current feels-like value and which index made it |
| `today_peak_stress`, `today_hours_danger` | Today's highest feels-like and danger hours |
| `thermal_score`, `risk` | Today's 0–100 score and band |
| `risk_score` | Relative risk (heat + population) |
| `forecast` | List of 5 day-dictionaries (`date_text`, `temp_max`, `stress`, `risk`, …) |
| `priority` | Score used to rank districts |
| `loaded` | `False` while waiting for weather (map shows grey) |

---

## 7. Weather (`weather.py`)

- **One request for all 37 districts.** Open-Meteo accepts many
  coordinates separated by commas, so we don't make 37 separate calls.
- **Hourly data** so we can count danger hours.
- **Cached for 60 minutes** in `data/weather_cache.json`.
- **Replay**: `get_replay_weather(locations, start)` fetches archived hourly
  weather from Open-Meteo's historical-forecast API and saves it to
  `data/replay_<date>.json`, so it works offline after the first time.
  "Current" conditions in a replay are 3 pm on the first day.
- **If the internet is down**, it uses a cache up to 24 hours old.
  If there isn't one, it uses made-up **DEMO** data. The screen always
  says which of these it's showing.

`get_weather(locations, force=False)` returns `(data, info)` where
`info["source"]` is `"Open-Meteo"`, `"Open-Meteo (cached)"`,
`"Open-Meteo (offline cache)"` or `"DEMO"`.

---

## 8. Alerts (`alerts.py`)

The idea: **don't cry wolf.** Only warn for a real heat wave (IMD criteria,
`heatwave.py`), and only when it shows up in more than one forecast update.
The UTCI band is not a trigger: normal Tamil Nadu summer days already reach
"extreme heat stress".

A day is a heat wave when Tmax is at least 40 °C (plains), 37 °C (coast) or
30 °C (hills) and 4.5 °C or more above the normal for that date (more than
6.4 °C = severe), or when Tmax is 45 °C or more (47 °C = severe). Normals come from
`data/tmax_normals.json` (`weather.get_tmax_normals()`).

```
District colour: YELLOW = 2 heat-wave days in a row, ORANGE = 2 severe days in a row
                 or 4+ heat-wave days in a row, RED = 3+ severe days in a row

Forecast update 1: district is YELLOW or above             → WATCH   (nothing sent)
Forecast update 2, ≥ 6 h later: still risky                 → WARNING (sent once)
Any update where it is no longer risky, or a gap > 36 h     → reset
```

Why 6 hours: the app downloads every hour, but the weather models behind
Open-Meteo publish a new run about every 6 hours. Two downloads an hour apart
are usually the *same* forecast, so they would not be a real confirmation
(`MIN_UPDATE_GAP_HOURS`, `MAX_UPDATE_GAP_HOURS` in `alerts.py`).

- `evaluate()` works out WATCH/WARNING for every district and remembers the
  count in `data/alert_state.json`. Only real, freshly downloaded forecasts
  count, not DEMO data or cache reloads.
- `dispatch()` sends the message to active city administrators whose
  **assigned district** matches and who have a mobile number.
- Real SMS/WhatsApp needs Twilio settings (environment variables
  `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`,
  optionally `TWILIO_WHATSAPP_FROM`). Without them, messages are only
  written to `data/alert_log.csv`. You can see them via **Log** in the left panel.

---

## 8b. The web API (`api.py`)

**What it is.** FastAPI turns Python functions into web addresses (URLs) that
return JSON. Any program – a React website, a phone app, another government
system – can ask it for the heat data without running the desktop app.

```bash
python api.py          # then open http://127.0.0.1:8000/docs
```

`/docs` is an automatic page listing every endpoint, with a "Try it out" button.

| Endpoint | Returns |
|---|---|
| `GET /districts` | All districts, most urgent first |
| `GET /districts/{name}` | One district: now, 5-day forecast, IMD code, alert, actions |
| `GET /alerts` | Current WATCH / WARNING list |
| `GET /alerts/log` | Sent/logged alerts (needs `X-API-Key` if `HEAT_API_KEY` is set) |
| `POST /refresh` | Download fresh weather now (same key rule) |
| `GET /replays` | Past heat waves; add `?replay=2024-04-30` to the calls above |
| `GET /geojson` | District boundaries for a web map |
| `GET /health` | Is it running, when was it last computed |

- **APScheduler** runs `refresh_live()` straight away and then every hour:
  recompute, update WATCH/WARNING, send newly confirmed warnings.
- It uses `service.compute_all()`, the same function the desktop app uses, so
  both always agree.
- Run the desktop app **or** the API as the alerting service, not both: they
  share `data/alert_state.json`.

---

## 9. Accounts and sign-in (`auth.py`)

- Accounts live in `data/users.json`.
- Passwords are **hashed** with PBKDF2 plus a random salt, so the file never
  contains the real password.
- `authenticate(username, password, role)` returns `(user, error_message)`.
- 5 wrong attempts → the account locks for 60 seconds.
- Passwords need 8+ characters, upper and lower case, and a number (`password_problems()`).
- `create_city_admin(...)`, `set_active(...)`, `reset_password(...)` are used by the Manage Access screen.
- `recipients_for(district)` is how alerts find the right officers.

> This is fine for a prototype on one computer. A real deployment would move
> accounts to a server with a database and proper sessions.

---

## 10. Screens (PyQt5 basics you need)

You only need three ideas to read the UI files:

1. **Widgets** are things on screen: `QLabel` (text), `QPushButton`,
   `QComboBox` (dropdown), `QLineEdit` (text box), `QFrame` (a box).
2. **Layouts** arrange widgets: `QVBoxLayout` stacks top-to-bottom,
   `QHBoxLayout` goes left-to-right, `QGridLayout` is rows and columns.
3. **Signals** connect actions to functions:
   ```python
   button.clicked.connect(self.load_weather)   # when clicked, run load_weather
   ```

### Where each part of the dashboard is built

| On screen | Code |
|---|---|
| Top bar (title, theme, text size, Sign out) | `MainWindow._build_top_bar()` in `main.py` |
| Left panel (map layer, alerts, priority list) | `MainWindow._build_left_panel()` |
| Summary tiles + map + district dropdown + legend | `MainWindow._build_centre()` |
| Right panel | `DetailPanel` in `panels.py` → `show_item()` |
| District banner at the top of the right panel | `HeroCard` |
| The four coloured number cards | `MetricCard` |
| 5-day line chart | `TrendChart` (drawn by hand with `QPainter`) |
| One row per forecast day | `ForecastRow` |
| Alert status + suggested actions | `ActionsCard` (text from `suggested_actions()` in `alerts.py`) |
| Population box | `CensusCard` |
| Map and hover card | `TamilNaduMap` in `map_view.py` |
| Sign-in / New account / Manage Access | `LoginDialog`, `AdminUserDialog`, `AccessManagerDialog` in `login.py` |

---

## 11. Styling: colours, themes and text size (`config.py`)

### Themes (light/dark)

Colours are **not** typed directly into the UI code. Styles use
`$names` that are swapped for the current theme's colours:

```python
set_base_style(label, "color:$muted; background:$surface; font-size:15px;")
```

- `THEMES["light"]` and `THEMES["dark"]` in `config.py` hold the actual colours.
- `set_base_style()` remembers the original style, then fills in the colours
  and scales the font size.
- When you switch theme or text size, `restyle()` re-applies every remembered
  style. Widgets that draw themselves (map, chart, legend) have an
  `on_theme_changed()` method that gets called too.

**Rule of thumb:** when you add a new widget, style it with
`set_base_style(...)` and `$tokens`, never `widget.setStyleSheet(...)`
with fixed colours. Otherwise it won't follow dark mode or text size.

### Screen sizes

- `main()` tells Qt to follow Windows scaling exactly (`PassThrough`), so 150 %
  stays 150 % instead of being rounded to 200 %.
- `MainWindow.apply_breakpoints()` runs on every resize. Below `COMPACT_WIDTH`
  it hides the subtitle and map hint, shortens the theme button and name badge,
  and narrows the right panel. Below `NARROW_WIDTH` it collapses the side panel
  and hides the name badge.
- Dialogs use `fit_to_screen()` (`ui_controls.py`) so they never open bigger
  than the screen; long forms scroll.
- The "?" button Windows adds to dialogs is turned off
  (`AA_DisableWindowContextHelpButton`).

### Text size

Font sizes are constants (`FS_SMALL = 13`, `FS_BODY = 15`, …). The A−/A+
buttons change a multiplier (100%–160%), and every `font-size:NNpx` is
multiplied by it. For sizes in drawing code, use `scaled(px)`.

### Heat colours

- `temperature_color(t)` → a colour between blue (15°C) and deep red (45°C).
- `risk_color(score)` → the same idea for 0–100 scores.
- `temperature_gradient(t)` / `risk_gradient(score)` → a **pair** of colours
  for a gradient **plus** a text colour (white or dark) that's guaranteed
  readable (contrast ≥ 4.5:1) on both ends.

---

## 12. Common changes – where to make them

| I want to… | Change this |
|---|---|
| Change the risk band cut-offs | `risk_band()` in `thermal.py` |
| Change how much duration matters | `combined_thermal_score()` and `DURATION_FULL_HOURS` in `thermal.py` |
| Change the heat vs population weighting | `relative_risk_score()` in `thermal.py` |
| Change the suggested actions text | `suggested_actions()` in `alerts.py` (used by the app, SMS and API) |
| Add an API endpoint | a new `@app.get(...)` function in `api.py` |
| Warn after 3 updates instead of 2 | `CONFIRM_UPDATES` in `alerts.py` |
| Change how far apart updates must be | `MIN_UPDATE_GAP_HOURS` / `MAX_UPDATE_GAP_HOURS` in `alerts.py` |
| Add another replay event | `REPLAY_EVENTS` in `config.py` (start date, label) |
| Change when the layout gets compact | `COMPACT_WIDTH`, `NARROW_WIDTH`, `RIGHT_PANEL_*` in `config.py` |
| Change the heat-wave thresholds or colour rules | constants and `district_code()` in `heatwave.py` |
| Mark a district as coastal / hills | `COASTAL` / `HILLS` in `heatwave.py` |
| Refresh weather more/less often | `WEATHER_CACHE_MINUTES` in `config.py` |
| Change a colour | `THEMES` in `config.py` (both light and dark) |
| Change default font sizes | `FS_*` constants in `config.py` |
| Add a new number card | `cards = [...]` list in `DetailPanel.show_item()` (`panels.py`) |
| Add a field to officer accounts | `create_city_admin()` in `auth.py` + `AdminUserDialog` in `login.py` |
| Swap districts for wards | Replace `data/tamil_nadu.geojson` with ward shapes; add a ward-level population CSV |

---

## 13. Glossary

| Term | Meaning |
|---|---|
| **UTCI** | Universal Thermal Climate Index – "feels like" temperature using temperature, humidity, wind and sun |
| **Heat index** | "Feels like" using temperature and humidity (NOAA/NWS formula) |
| **Thermal score** | 0–100: peak feels-like (75%) + hours in danger (25%) |
| **Relative risk** | 0–100: thermal score (70%) + population exposure (30%) |
| **Danger range** | Heat index ≥ 39.4°C or UTCI ≥ 38°C |
| **Heat wave (IMD)** | Tmax well above the local normal (see §8); colour YELLOW / ORANGE / RED |
| **WATCH / WARNING** | IMD heat wave seen in 1 update / confirmed in 2 updates in a row (≥ 6 h apart) |
| **Replay** | Archived weather for a past heat wave, shown as if it were the forecast |
| **Priority score** | Used to rank which districts need attention first |
| **GeoJSON** | A text file format for map shapes |
| **Thread / worker** | Code running in the background so the window stays responsive |
| **Hash (password)** | A one-way scramble of a password; you can check it but not reverse it |
| **Token (`$surface`)** | A placeholder in a style that becomes a real colour for the current theme |
