"""
Heat Intelligence web API – the FastAPI backend from the idea submission.

Serves the same numbers as the desktop app (both use service.py) as JSON, so a
web dashboard (React + Leaflet), a mobile app or another government system can
use them. APScheduler recomputes every hour, and confirmed WARNINGs are sent to
the assigned officers exactly as in the desktop app (alerts.py).

Run:   python api.py            → interactive docs at http://127.0.0.1:8000/docs
       (or: python -m uvicorn api:app --port 8000)

Settings (environment variables, all optional):
  HEAT_API_KEY   if set, POST /refresh and GET /alerts/log need the header X-API-Key
  HEAT_API_HOST  default 127.0.0.1 (this computer only); 0.0.0.0 to share on a network
  HEAT_API_PORT  default 8000
  HEAT_API_CORS  comma-separated web origins allowed to call the API
                 (default: the React/Vite dev servers on localhost:3000 and :5173)
  TWILIO_*       as for the desktop app (alerts.py)

Run either the desktop app or the API as the alerting service, not both at
once: they share data/alert_state.json, and although a WARNING is only sent
once, two processes updating the file at the same moment can race.
"""
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import alerts as alert_engine
from auth import AuthManager
from config import APP_VERSION, MAP_FILE, REPLAY_EVENTS, STATE_NAME, WEATHER_CACHE_MINUTES
from heatwave import code_index
from service import compute_all, load_areas
from thermal import engine_name

API_KEY = os.environ.get("HEAT_API_KEY")
REPLAYS = dict(REPLAY_EVENTS)
FIRST_LOAD_WAIT_SECONDS = 60

_lock = threading.Lock()
_ready = threading.Event()
_snapshots = {}          # None (live) or replay start date → snapshot dict
_areas = None


def _get_areas():
    global _areas
    if _areas is None:
        _areas = load_areas()
    return _areas


def _snapshot(results, info, alert_list):
    return {"results": results, "info": info, "alerts": alert_list,
            "computed_at": datetime.now().isoformat(timespec="seconds")}


def refresh_live(force=False):
    """Scheduler job: recompute, update WATCH/WARNING, send newly confirmed warnings."""
    locations, demographics, capacities = _get_areas()
    results, info = compute_all(locations, demographics, capacities, force=force)
    alert_list, newly_confirmed = alert_engine.evaluate(results, info)
    if newly_confirmed:
        auth = AuthManager()
        for alert in newly_confirmed:
            alert_engine.dispatch(alert, auth.recipients_for(alert["district"]),
                                  alert_engine.suggested_actions(results[alert["district"]]))
    with _lock:
        _snapshots[None] = _snapshot(results, info, alert_list)
    _ready.set()


def _load_replay(start):
    locations, demographics, capacities = _get_areas()
    results, info = compute_all(locations, demographics, capacities, replay=start)
    alert_list, _ = alert_engine.evaluate(results, info)      # replay: never stored or sent
    return _snapshot(results, info, alert_list)


def current(replay=None):
    """Latest snapshot for live data or a replay; errors as HTTP responses."""
    if replay:
        if replay not in REPLAYS:
            raise HTTPException(404, f"Unknown replay '{replay}'. See GET /replays.")
        with _lock:
            snap = _snapshots.get(replay)
        if snap is None:
            snap = _load_replay(replay)
            if snap["results"]:
                with _lock:
                    _snapshots[replay] = snap
    else:
        if not _ready.wait(FIRST_LOAD_WAIT_SECONDS):
            raise HTTPException(503, "Weather is still loading – try again in a few seconds.",
                                headers={"Retry-After": "10"})
        with _lock:
            snap = _snapshots[None]
    if not snap["results"]:
        raise HTTPException(503, snap["info"].get("error") or "No weather data available.")
    return snap


def require_key(x_api_key: str = Header(default=None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "Missing or wrong X-API-Key header.")


def _find(results, name):
    for district, metrics in results.items():
        if district.lower() == name.lower():
            return district, metrics
    raise HTTPException(404, f"No district called '{name}'. See GET /districts.")


def _summary(name, m):
    return {
        "district": name,
        "imd_code": m["imd"]["code"],
        "imd_label": m["imd"]["label"],
        "temperature": m["temperature"],
        "humidity": m["humidity"],
        "feels_like_now": m["stress"],
        "feels_like_peak_today": m["today_peak_stress"],
        "stress_model": m["stress_model"],
        "hours_in_danger_today": m["today_hours_danger"],
        "heat_stress_band": m["risk"],
        "thermal_score": m["thermal_score"],
        "relative_risk": m["risk_score"],
        "priority": m["priority"],
        "population_2011": m["demographic"].get("population", 0),
        "terrain": m["terrain"],
    }


def _source(snap):
    info = snap["info"]
    return {
        "source": info.get("source"),
        "replay": info.get("replay"),
        "weather_time": datetime.fromtimestamp(info.get("fetched_at", time.time())).isoformat(timespec="seconds"),
        "computed_at": snap["computed_at"],
        "thermal_engine": engine_name(),
        "normals_loaded": info.get("normals", 0),
    }


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app):
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    # First run straight away, then every hour (the PDF's "refresh every hour").
    scheduler.add_job(refresh_live, "interval", minutes=WEATHER_CACHE_MINUTES,
                      next_run_time=datetime.now(), id="refresh_live", max_instances=1, coalesce=True)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Heat Intelligence API",
    version=APP_VERSION,
    description=(f"Extreme heatwave early warning and human thermal stress index for {STATE_NAME} "
                 "(SIH 2026, PS 26083). District level in this prototype; ward-ready. "
                 "Add `?replay=2024-04-30` to most endpoints to see the archived 2024 heat wave."),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get(
        "HEAT_API_CORS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

REPLAY_QUERY = Query(default=None, description="Replay start date from GET /replays; omit for live data")


@app.get("/", tags=["info"])
def root():
    return {"name": "Heat Intelligence API", "version": APP_VERSION, "state": STATE_NAME,
            "docs": "/docs", "ready": _ready.is_set()}


@app.get("/health", tags=["info"])
def health():
    with _lock:
        live = _snapshots.get(None)
    return {"ok": True, "ready": _ready.is_set(),
            "computed_at": live["computed_at"] if live else None,
            "alert_gateway": alert_engine.gateway_status() or "not configured (alerts are logged only)"}


@app.get("/replays", tags=["info"])
def replays():
    """Past heat waves that can be replayed with ?replay=<start>."""
    return [{"start": start, "label": label} for start, label in REPLAY_EVENTS]


@app.get("/districts", tags=["districts"])
def districts(replay: str = REPLAY_QUERY):
    """Every district, most urgent first (IMD code, then priority score)."""
    snap = current(replay)
    ranked = sorted(snap["results"].items(),
                    key=lambda kv: (code_index(kv[1]["imd"]["code"]), kv[1]["priority"]), reverse=True)
    return {**_source(snap), "districts": [_summary(n, m) for n, m in ranked]}


@app.get("/districts/{name}", tags=["districts"])
def district(name: str, replay: str = REPLAY_QUERY):
    """Full detail for one district: current conditions, 5-day forecast, IMD code, actions."""
    snap = current(replay)
    district_name, m = _find(snap["results"], name)
    alert = next((a for a in snap["alerts"] if a["district"] == district_name), None)
    return {**_source(snap), **_summary(district_name, m),
            "wind_ms": m["wind"], "solar_wm2": m["solar"], "heat_index_now": m["heat_index"],
            "vulnerability": m["vulnerability"], "response_capacity": m["capacity"],
            "imd": m["imd"], "forecast": m["forecast"], "alert": alert,
            "suggested_actions": alert_engine.suggested_actions(m),
            "census_note": m["demographic"].get("note")}


@app.get("/alerts", tags=["alerts"])
def alerts(replay: str = REPLAY_QUERY):
    """Current WATCH / WARNING list (IMD heat-wave criteria, confirmed across forecast updates)."""
    snap = current(replay)
    return {**_source(snap), "alerts": snap["alerts"]}


@app.get("/alerts/log", tags=["alerts"], dependencies=[Depends(require_key)])
def alert_log(limit: int = Query(default=50, ge=1, le=500)):
    """Alerts that were sent or logged, newest first. Contains officer names – protect with HEAT_API_KEY."""
    return alert_engine.read_log(limit)


@app.post("/refresh", tags=["alerts"], dependencies=[Depends(require_key)])
def refresh():
    """Download fresh weather now and re-check alerts (normally done every hour)."""
    refresh_live(force=True)
    with _lock:
        return _source(_snapshots[None])


@app.get("/geojson", tags=["map"])
def geojson():
    """District boundaries, for drawing the map in a web frontend (e.g. Leaflet)."""
    return FileResponse(MAP_FILE, media_type="application/geo+json")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HEAT_API_HOST", "127.0.0.1"),
                port=int(os.environ.get("HEAT_API_PORT", "8000")))
