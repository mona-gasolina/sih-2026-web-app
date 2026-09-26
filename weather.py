"""
Weather data: Open-Meteo (free, no API key).

• One batched request for every district (Open-Meteo accepts comma-separated
  coordinates), instead of one request per district – addresses the
  "overflow of API calls" risk in the idea submission.
• Hourly data, so thermal stress can be computed hour-by-hour and the
  duration of dangerous exposure can be measured.
• Responses are cached on disk for WEATHER_CACHE_MINUTES (1 hour) – the
  "cache weather data and refresh every hour" strategy from the PDF.
"""
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from config import (
    OPEN_METEO_URL, WEATHER_TIMEOUT, WEATHER_CACHE_FILE, WEATHER_CACHE_MINUTES,
    FORECAST_DAYS, DATA_DIR, NORMALS_FILE, NORMALS_URL, NORMALS_YEARS, NORMALS_SMOOTH_DAYS,
)

HOURLY_VARS = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "shortwave_radiation"]


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
    return {name: payload for (name, _, _), payload in zip(locations, data)}


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
        date = stamp[:10]
        days.setdefault(date, []).append({
            "time": stamp,
            "temperature": _num(hourly.get("temperature_2m", []), i),
            "humidity": _num(hourly.get("relative_humidity_2m", []), i),
            "wind": _num(hourly.get("wind_speed_10m", []), i) / 3.6,      # km/h → m/s
            "solar": _num(hourly.get("shortwave_radiation", []), i),
        })
    return {
        "current": {
            "temperature": float(current.get("temperature_2m") or 0.0),
            "humidity": float(current.get("relative_humidity_2m") or 0.0),
            "wind": float(current.get("wind_speed_10m") or 0.0) / 3.6,
            "solar": float(current.get("shortwave_radiation") or 0.0),
            "time": current.get("time", ""),
        },
        "days": [{"date": d, "hours": h} for d, h in sorted(days.items())],
    }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def load_cache(names, max_age_minutes=WEATHER_CACHE_MINUTES):
    try:
        cache = json.loads(WEATHER_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    age = (time.time() - cache.get("fetched_at", 0)) / 60.0
    if age > max_age_minutes or sorted(cache.get("names", [])) != sorted(names):
        return None
    return cache


def save_cache(payloads):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        WEATHER_CACHE_FILE.write_text(json.dumps({
            "fetched_at": time.time(),
            "names": list(payloads.keys()),
            "payloads": payloads,
        }), encoding="utf-8")
    except Exception:
        pass


def get_weather(locations, force=False):
    """
    Returns (normalised {name: data}, info dict).
    info = {"source": "Open-Meteo" | "Open-Meteo (cached)" | "DEMO", "fetched_at": epoch, "fresh": bool, "error": str}
    """
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
        # Stale cache is better than invented numbers.
        cache = load_cache(names, max_age_minutes=24 * 60)
        if cache:
            return ({n: normalize(p) for n, p in cache["payloads"].items()},
                    {"source": "Open-Meteo (offline cache)", "fetched_at": cache["fetched_at"],
                     "fresh": False, "error": str(exc)})
        return ({n: demo_weather(i) for i, n in enumerate(names)},
                {"source": "DEMO", "fetched_at": time.time(), "fresh": False, "error": str(exc)})


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
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        NORMALS_FILE.write_text(json.dumps({
            "source": f"Open-Meteo historical forecast API, daily max temperature {first}-{last}, "
                      f"day-of-year mean smoothed ±{NORMALS_SMOOTH_DAYS} days",
            "normals": normals,
        }), encoding="utf-8")
    except Exception:
        pass
    return normals


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
                "wind": 2.0, "solar": round(solar, 1),
            })
        days.append({"date": (start + timedelta(days=d)).strftime("%Y-%m-%d"), "hours": hours})
    now_h = datetime.now().hour
    return {"current": dict(days[0]["hours"][now_h]), "days": days}
