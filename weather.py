"""
Weather data: Open-Meteo (free, no API key).

• One batched request for every district (Open-Meteo accepts comma-separated
  coordinates), instead of one request per district – addresses the
  "overflow of API calls" risk in the idea submission.
• Hourly data, so thermal stress can be computed hour-by-hour and the
  duration of dangerous exposure can be measured.
• Responses are cached on disk for WEATHER_CACHE_MINUTES (1 hour) – the
  "cache weather data and refresh every hour" strategy from the PDF.
• Replay: archived weather for a past heat wave (get_replay_weather), so the
  warning flow can be demonstrated outside the heat season.
"""
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from config import (
    atomic_write_text,
    OPEN_METEO_URL, WEATHER_TIMEOUT, WEATHER_CACHE_FILE, WEATHER_CACHE_MINUTES,
    FORECAST_DAYS, DATA_DIR, NORMALS_FILE, NORMALS_URL, NORMALS_YEARS, NORMALS_SMOOTH_DAYS,
    ENSEMBLE_MODELS, MODEL_BIAS_FILE, MODEL_BIAS_START,
)

HOURLY_VARS = [
    "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
    "shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation",   # sun: total, direct, scattered
    "cloud_cover", "soil_temperature_0cm",                                    # clouds; ground surface temperature
]
CACHE_VERSION = 2          # bump when HOURLY_VARS changes, so old caches are re-downloaded


def _request(params, base_url=OPEN_METEO_URL, timeout=WEATHER_TIMEOUT):
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "HeatIntelligencePrototype/0.3"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_batch(locations, days=FORECAST_DAYS):
    """locations: list of (name, lat, lon). Returns {name: raw payload}."""
    params = {
        "latitude": ",".join(f"{lat:.4f}" for _, lat, _ in locations),
        "longitude": ",".join(f"{lon:.4f}" for _, _, lon in locations),
        "forecast_days": days,
        "timezone": "Asia/Kolkata",
        "current": ",".join(HOURLY_VARS),
        "hourly": ",".join(HOURLY_VARS),
    }
    data = _request(params)
    if isinstance(data, dict):
        data = [data]
    if len(data) != len(locations):
        raise RuntimeError("Unexpected number of locations in weather response")
    payloads = {name: payload for (name, _, _), payload in zip(locations, data)}
    _attach_models(payloads, locations, {"forecast_days": days})
    return payloads


def _attach_models(payloads, locations, window, base_url=OPEN_METEO_URL):
    """
    Adds each model's daily max temperature (ECMWF, GFS, ICON) to every payload
    as payload["models_daily"]. Optional: if it fails, alerts use the main
    forecast only and say so.
    """
    try:
        data = _request({
            "latitude": ",".join(f"{lat:.4f}" for _, lat, _ in locations),
            "longitude": ",".join(f"{lon:.4f}" for _, _, lon in locations),
            "timezone": "Asia/Kolkata",
            "daily": "temperature_2m_max",
            "models": ",".join(ENSEMBLE_MODELS),
            **window,
        }, base_url=base_url)
        if isinstance(data, dict):
            data = [data]
        for (name, _, _), payload in zip(locations, data):
            payloads[name]["models_daily"] = payload.get("daily", {})
    except Exception:
        pass


def _num(values, i, default=0.0):
    try:
        v = values[i]
        return default if v is None else float(v)
    except (IndexError, TypeError, ValueError):
        return default


def normalize(payload):
    """Raw Open-Meteo payload → {"current": {...}, "days": [{"date", "hours": [...]}, ...]}"""
    current = payload.get("current", {})
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    days = {}
    for i, stamp in enumerate(times):
        days.setdefault(stamp[:10], []).append(_hour(hourly, i, stamp, 60))
    now = _hour({k: [v] for k, v in current.items()}, 0, current.get("time", ""),
                (current.get("interval") or 900) / 60.0)
    return {
        "current": now,
        "days": [{"date": d, "hours": h} for d, h in sorted(days.items())],
        "lat": payload.get("latitude"),
        "lon": payload.get("longitude"),
        "model_tmax": _model_tmax(payload.get("models_daily") or {}),
    }


def _hour(src, i, stamp, avg_minutes):
    """One hour of weather in the units the thermal engine uses."""
    ground = src.get("soil_temperature_0cm", [None])
    return {
        "time": stamp,
        "avg_minutes": avg_minutes,             # radiation is the mean over this many minutes before "time"
        "temperature": _num(src.get("temperature_2m", []), i),
        "humidity": _num(src.get("relative_humidity_2m", []), i),
        "wind": _num(src.get("wind_speed_10m", []), i) / 3.6,          # km/h → m/s
        "solar": _num(src.get("shortwave_radiation", []), i),          # global horizontal, W/m²
        "dni": _num(src.get("direct_normal_irradiance", []), i),       # direct sun, W/m²
        "diffuse": _num(src.get("diffuse_radiation", []), i),          # scattered sky light, W/m²
        "cloud": _num(src.get("cloud_cover", []), i),                  # %
        "ground_temp": _num(ground, i, None) if i < len(ground) else None,   # °C
    }


def _model_tmax(daily):
    """{"time": [...], "temperature_2m_max_<model>": [...]} → {model: {date: tmax}}"""
    result = {}
    for model in ENSEMBLE_MODELS:
        values = daily.get(f"temperature_2m_max_{model}") or []
        series = {d: v for d, v in zip(daily.get("time", []), values) if v is not None}
        if series:
            result[model] = series
    return result


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def load_cache(names, max_age_minutes=WEATHER_CACHE_MINUTES):
    try:
        cache = json.loads(WEATHER_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    age = (time.time() - cache.get("fetched_at", 0)) / 60.0
    if (age > max_age_minutes or sorted(cache.get("names", [])) != sorted(names)
            or cache.get("version") != CACHE_VERSION):
        return None
    return cache


def save_cache(payloads):
    try:
        atomic_write_text(WEATHER_CACHE_FILE, json.dumps({
            "fetched_at": time.time(),
            "version": CACHE_VERSION,
            "names": list(payloads.keys()),
            "payloads": payloads,
        }))
    except Exception:
        pass


def get_weather(locations, force=False, replay=None):
    """
    Returns (normalised {name: data}, info dict).
    info = {"source": "Open-Meteo" | "Open-Meteo (cached)" | "DEMO" | "REPLAY …", "fetched_at": epoch,
            "fresh": bool, "error": str, "replay": start date or None}
    """
    if replay:
        return get_replay_weather(locations, replay)
    names = [n for n, _, _ in locations]
    if not force:
        cache = load_cache(names)
        if cache:
            return ({n: normalize(p) for n, p in cache["payloads"].items()},
                    {"source": "Open-Meteo (cached)", "fetched_at": cache["fetched_at"], "fresh": False, "error": ""})
    try:
        payloads = fetch_batch(locations)
        save_cache(payloads)
        return ({n: normalize(p) for n, p in payloads.items()},
                {"source": "Open-Meteo", "fetched_at": time.time(), "fresh": True, "error": ""})
    except Exception as exc:
        print(f"Weather download failed: {exc!r}", flush=True)
        # Stale cache is better than invented numbers.
        cache = load_cache(names, max_age_minutes=24 * 60)
        if cache:
            return ({n: normalize(p) for n, p in cache["payloads"].items()},
                    {"source": "Open-Meteo (offline cache)", "fetched_at": cache["fetched_at"],
                     "fresh": False, "error": str(exc)})
        return ({n: demo_weather(i) for i, n in enumerate(names)},
                {"source": "DEMO", "fetched_at": time.time(), "fresh": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Replay of a past period (archived weather)
# ---------------------------------------------------------------------------
REPLAY_HOUR = 15          # "current" conditions in a replay = 3 pm on the first day


def get_replay_weather(locations, start, days=FORECAST_DAYS):
    """
    Archived hourly weather for `days` days from `start` (YYYY-MM-DD), shaped like a
    live forecast. Saved to data/replay_<start>.json on first use (the archive does
    not change), so a replay also works offline once it has been opened.
    """
    names = [n for n, _, _ in locations]
    path = DATA_DIR / f"replay_{start}.json"
    info = {"source": f"REPLAY {start}", "fetched_at": time.time(), "fresh": False, "error": "", "replay": start}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
        if sorted(cache.get("names", [])) == sorted(names) and cache.get("version") == CACHE_VERSION:
            return {n: _replay_normalize(p) for n, p in cache["payloads"].items()}, info
    except Exception:
        pass
    end = (datetime.strptime(start, "%Y-%m-%d") + timedelta(days=days - 1)).strftime("%Y-%m-%d")
    try:
        data = _request({
            "latitude": ",".join(f"{lat:.4f}" for _, lat, _ in locations),
            "longitude": ",".join(f"{lon:.4f}" for _, _, lon in locations),
            "start_date": start, "end_date": end,
            "timezone": "Asia/Kolkata",
            "hourly": ",".join(HOURLY_VARS),
        }, base_url=NORMALS_URL, timeout=90)
        if isinstance(data, dict):
            data = [data]
        if len(data) != len(locations):
            raise RuntimeError("Unexpected number of locations in replay response")
        payloads = {name: payload for name, payload in zip(names, data)}
        _attach_models(payloads, locations, {"start_date": start, "end_date": end}, base_url=NORMALS_URL)
        try:
            atomic_write_text(path, json.dumps({"start": start, "version": CACHE_VERSION, "names": names,
                                                "payloads": payloads}))
        except Exception:
            pass
        return {n: _replay_normalize(p) for n, p in payloads.items()}, info
    except Exception as exc:
        # No archive and no internet: nothing honest to show, so say so.
        info["error"] = f"Replay data could not be downloaded: {exc}"
        return {}, info


def _replay_normalize(payload):
    data = normalize(payload)
    first = data["days"][0]["hours"] if data["days"] else []
    if first:
        hour = dict(first[min(REPLAY_HOUR, len(first) - 1)])
        data["current"] = hour
    return data


# ---------------------------------------------------------------------------
# Daily-max normals (for the IMD heat-wave departure test)
# ---------------------------------------------------------------------------
def _build_normals(daily):
    """Daily Tmax series → 365 smoothed day-of-year means (non-leap calendar)."""
    sums, counts = [0.0] * 365, [0] * 365
    for stamp, value in zip(daily.get("time", []), daily.get("temperature_2m_max", [])):
        if value is None:
            continue
        d = datetime.strptime(stamp, "%Y-%m-%d")
        day = 28 if (d.month, d.day) == (2, 29) else d.day
        i = datetime(2001, d.month, day).timetuple().tm_yday - 1
        sums[i] += value
        counts[i] += 1
    w = NORMALS_SMOOTH_DAYS
    result = []
    for i in range(365):
        window = [(i + k) % 365 for k in range(-w, w + 1)]
        n = sum(counts[j] for j in window)
        result.append(round(sum(sums[j] for j in window) / n, 1) if n else None)
    return result if all(v is not None for v in result) else None


def get_tmax_normals(locations):
    """
    Returns {name: [365 daily Tmax normals]} for as many districts as possible.
    Built once from Open-Meteo's archive of past forecasts and kept in
    data/tmax_normals.json (bundled with the prototype, so it also works offline).
    Missing districts → no departure test, only the absolute 45/47 °C rule.
    """
    try:
        cached = json.loads(NORMALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        cached = {}
    normals = cached.get("normals", {})
    missing = [loc for loc in locations if loc[0] not in normals]
    if not missing:
        return normals
    try:
        first, last = NORMALS_YEARS
        data = _request({
            "latitude": ",".join(f"{lat:.4f}" for _, lat, _ in missing),
            "longitude": ",".join(f"{lon:.4f}" for _, _, lon in missing),
            "start_date": f"{first}-01-01",
            "end_date": f"{last}-12-31",
            "daily": "temperature_2m_max",
            "timezone": "Asia/Kolkata",
        }, base_url=NORMALS_URL, timeout=90)
        if isinstance(data, dict):
            data = [data]
        for (name, _, _), payload in zip(missing, data):
            series = _build_normals(payload.get("daily", {}))
            if series:
                normals[name] = series
        atomic_write_text(NORMALS_FILE, json.dumps({
            "source": f"Open-Meteo historical forecast API, daily max temperature {first}-{last}, "
                      f"day-of-year mean smoothed ±{NORMALS_SMOOTH_DAYS} days",
            "normals": normals,
        }))
    except Exception:
        pass
    return normals


# ---------------------------------------------------------------------------
# Model bias (each weather model runs a little warm or cool)
# ---------------------------------------------------------------------------
BIAS_WINDOW_DAYS = 30        # ± days pooled for each day of the year
BIAS_MIN_SAMPLES = 20


def get_model_bias(locations):
    """
    Returns {district: {model: [365 daily offsets vs the main forecast]}}.

    The IMD test compares Tmax with a normal built from the main (best-match)
    forecast archive. ECMWF, GFS and ICON each run warmer or cooler than that
    (e.g. ~1 °C in May 2024), so before comparing a model with the normal its
    typical offset for that time of year is removed. Offsets come from the
    archive of past forecasts since MODEL_BIAS_START; built once and kept in
    data/model_bias.json.
    """
    try:
        cached = json.loads(MODEL_BIAS_FILE.read_text(encoding="utf-8"))
    except Exception:
        cached = {}
    bias = cached.get("bias", {})
    missing = [loc for loc in locations if loc[0] not in bias]
    if not missing:
        return bias
    end = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        data = _request({
            "latitude": ",".join(f"{lat:.4f}" for _, lat, _ in missing),
            "longitude": ",".join(f"{lon:.4f}" for _, _, lon in missing),
            "start_date": MODEL_BIAS_START, "end_date": end,
            "daily": "temperature_2m_max",
            "models": ",".join(["best_match", *ENSEMBLE_MODELS]),
            "timezone": "Asia/Kolkata",
        }, base_url=NORMALS_URL, timeout=120)
        if isinstance(data, dict):
            data = [data]
        for (name, _, _), payload in zip(missing, data):
            daily = payload.get("daily", {})
            ref = daily.get("temperature_2m_max_best_match") or []
            per_model = {}
            for model in ENSEMBLE_MODELS:
                series = _bias_series(daily.get("time", []), ref, daily.get(f"temperature_2m_max_{model}") or [])
                if series:
                    per_model[model] = series
            bias[name] = per_model
        atomic_write_text(MODEL_BIAS_FILE, json.dumps({
            "source": f"Open-Meteo historical forecast API, daily Tmax {MODEL_BIAS_START} to {end}: "
                      f"model minus best_match, day-of-year mean ±{BIAS_WINDOW_DAYS} days",
            "bias": bias,
        }))
    except Exception:
        pass
    return bias


def _bias_series(times, ref, values):
    sums, counts = [0.0] * 365, [0] * 365
    for stamp, r, v in zip(times, ref, values):
        if r is None or v is None:
            continue
        d = datetime.strptime(stamp, "%Y-%m-%d")
        day = 28 if (d.month, d.day) == (2, 29) else d.day
        i = datetime(2001, d.month, day).timetuple().tm_yday - 1
        sums[i] += v - r
        counts[i] += 1
    result = []
    for i in range(365):
        window = [(i + k) % 365 for k in range(-BIAS_WINDOW_DAYS, BIAS_WINDOW_DAYS + 1)]
        n = sum(counts[j] for j in window)
        result.append(round(sum(sums[j] for j in window) / n, 2) if n >= BIAS_MIN_SAMPLES else 0.0)
    return result if any(counts) else None


# ---------------------------------------------------------------------------
# Offline demo data (clearly labelled DEMO in the UI)
# ---------------------------------------------------------------------------
def demo_weather(index=0):
    """Synthetic diurnal curves so the dashboard can be demonstrated offline."""
    base_max = [34.5, 36.0, 37.5, 36.5, 33.5]
    offset = (index % 9) * 0.4 - 1.6
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days = []
    for d, tmax in enumerate(base_max):
        hours = []
        for h in range(24):
            phase = math.cos((h - 15) / 24 * 2 * math.pi)       # peak ~3 pm
            temp = tmax + offset - 9 + 9 * (phase + 1) / 2
            rh = 82 - 36 * (phase + 1) / 2
            solar = max(0.0, 900 * math.sin((h - 6) / 12 * math.pi)) if 6 <= h <= 18 else 0.0
            hours.append({
                "time": (start + timedelta(days=d, hours=h)).strftime("%Y-%m-%dT%H:%M"),
                "temperature": round(temp, 1), "humidity": round(rh, 1),
                "wind": 2.0, "solar": round(solar, 1), "avg_minutes": 60,
                "dni": round(solar * 0.8, 1), "diffuse": round(solar * 0.15, 1), "cloud": 20.0,
                "ground_temp": round(temp + solar / 60.0, 1),
            })
        days.append({"date": (start + timedelta(days=d)).strftime("%Y-%m-%d"), "hours": hours})
    now_h = datetime.now().hour
    return {"current": dict(days[0]["hours"][now_h]), "days": days, "lat": None, "lon": None,
            "model_tmax": {}}
