"""
Heat Intelligence web API – the FastAPI backend from the idea submission.

Serves the same numbers as the desktop app (both use service.py) as JSON, so a
web dashboard (React + Leaflet), a mobile app or another government system can
use them. APScheduler recomputes every hour, and confirmed WARNINGs are sent to
the assigned officers exactly as in the desktop app (alerts.py).

Run:   python api.py            → web dashboard at http://127.0.0.1:8000/app/
                                  interactive docs at http://127.0.0.1:8000/docs
       (or: python -m uvicorn api:app --port 8000)

Access: the district and alert data need either a signed-in user (the web
dashboard signs in with the desktop app's accounts: POST /auth/login sets an
HttpOnly session cookie) or the X-API-Key header for other systems. The alert log
(officer names) is for the System Admin or the API key only.

Settings (environment variables, all optional):
  HEAT_API_KEY   key other systems send as the X-API-Key header (no key set = sign-in only)
  HEAT_API_HOST  default 127.0.0.1 (this computer only); 0.0.0.0 to share on a network
  HEAT_API_PORT  default 8000 (or PORT, which hosting services such as Render set)
  HEAT_ADMIN_PASSWORD  password of the first System Admin account (default Admin@123)
  HEAT_TRUST_PROXY  1 behind a hosting service's HTTPS proxy, so session cookies are Secure
  HEAT_API_CORS  comma-separated web origins allowed to call the API
                 (default: the React/Vite dev servers on localhost:3000 and :5173)
  TWILIO_*       as for the desktop app (alerts.py)

The desktop app and the API can run at the same time on the same data folder:
they share data/alert_state.json and users.json through a file lock
(config.file_lock), so each WARNING is still sent exactly once.
"""
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import alerts as alert_engine
from auth import AuthManager
from config import (
    APP_VERSION, BASE_DIR, MAP_FILE, REPLAY_EVENTS, STATE_NAME, WEATHER_CACHE_MINUTES,
    THEMES, TEMP_GRADIENT_STOPS, RISK_GRADIENT_STOPS, RISK_ORDER, risk_band_color,
    BAND_LABELS, BAND_ADVICE, STRESS_LABELS,
)
from heatwave import code_index
from service import compute_all, load_areas
from thermal import engine_name

API_KEY = os.environ.get("HEAT_API_KEY")
WEB_DIR = BASE_DIR / "web"
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
                                  alert_engine.suggested_actions(results[alert["district"]], alert))
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


# ---------------------------------------------------------------------------
# Access: web sign-in (same accounts as the desktop app) or an API key
# ---------------------------------------------------------------------------
SESSION_COOKIE = "heat_session"
SESSION_SECONDS = 8 * 3600
_sessions = {}                 # token → {"user": public user fields, "expires": epoch seconds}
_sessions_lock = threading.Lock()
_auth_lock = threading.Lock()  # AuthManager rewrites users.json (failed attempts, last login)
PUBLIC_USER_FIELDS = ("username", "full_name", "designation", "role", "city", "district")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    role: str = Field(pattern="^(admin|city_admin)$", description="admin or city_admin")


def _session_user(request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with _sessions_lock:
        session = _sessions.get(token)
        if session and session["expires"] > time.time():
            return session["user"]
        _sessions.pop(token, None)
    return None


def _key_ok(x_api_key):
    return bool(API_KEY) and x_api_key is not None and secrets.compare_digest(x_api_key, API_KEY)


def require_access(request: Request, x_api_key: str = Header(default=None)):
    """A signed-in user, or another system with the API key."""
    if _key_ok(x_api_key):
        return {"username": "api-key", "role": "system"}
    user = _session_user(request)
    if user is None:
        raise HTTPException(401, "Please sign in.")
    return user


def require_admin(request: Request, x_api_key: str = Header(default=None)):
    """The System Admin, or the API key."""
    user = require_access(request, x_api_key)
    if user["role"] not in ("admin", "system"):
        raise HTTPException(403, "Only the System Admin can see this.")
    return user


def _find(results, name):
    for district, metrics in results.items():
        if district.lower() == name.lower():
            return district, metrics
    raise HTTPException(404, f"No district called '{name}'. See GET /districts.")


def _peak_day(m):
    """The hottest 'feels like' day in the forecast: (value, day text)."""
    days = m.get("forecast") or []
    best = max(days, key=lambda d: d["stress"], default=None)
    return (best["stress"], best["date_text"]) if best else (m["today_peak_stress"], "Today")


def _summary(name, m):
    peak, peak_day = _peak_day(m)
    return {
        "district": name,
        "imd_code": m["imd"]["code"],
        "imd_label": m["imd"]["label"],
        "temperature": m["temperature"],
        "humidity": m["humidity"],
        "cloud_cover": m.get("cloud"),
        "feels_like_now": m["stress"],
        "feels_like_peak_today": m["today_peak_stress"],
        "feels_like_peak_5day": peak,
        "feels_like_peak_day": peak_day,
        "stress_category_now": m["stress_category"],
        "stress_model": m["stress_model"],
        "hours_in_danger_today": m["today_hours_danger"],
        "heat_stress_band": m["risk"],
        "worst_band_5day": m["peak_band"],
        "thermal_score": m["thermal_score"],
        "relative_risk": m["risk_score"],
        "priority": m["priority"],
        "models_agreeing": m.get("ensemble", {}).get("agree"),
        "models_total": m.get("ensemble", {}).get("total"),
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
def root(request: Request):
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/app/")          # people opening the site go to the dashboard
    return {"name": "Heat Intelligence API", "version": APP_VERSION, "state": STATE_NAME,
            "dashboard": "/app/", "docs": "/docs", "ready": _ready.is_set()}


@app.post("/auth/login", tags=["auth"])
def login(body: LoginRequest, request: Request, response: Response):
    """Sign in with a desktop-app account; sets an HttpOnly session cookie for 8 hours."""
    with _auth_lock:
        user, message = AuthManager().authenticate(body.username.strip(), body.password, body.role)
    if not user:
        raise HTTPException(401, message)
    public = {k: user.get(k, "") for k in PUBLIC_USER_FIELDS}
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _sessions_lock:
        for old in [t for t, sess in _sessions.items() if sess["expires"] <= now]:
            del _sessions[old]
        _sessions[token] = {"user": public, "expires": now + SESSION_SECONDS}
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        samesite="strict", secure=request.url.scheme == "https", path="/")
    return public


@app.post("/auth/logout", tags=["auth"])
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with _sessions_lock:
            _sessions.pop(token, None)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/auth/me", tags=["auth"])
def me(user: dict = Depends(require_access)):
    return user


@app.get("/ui/config", tags=["info"])
def ui_config():
    """Colours and scales shared with the desktop app, so the web map looks the same."""
    return {
        "app_version": APP_VERSION,
        "state": STATE_NAME,
        "themes": THEMES,
        "temperature_stops": TEMP_GRADIENT_STOPS,
        "risk_stops": RISK_GRADIENT_STOPS,
        "band_colours": {band: risk_band_color(band)
                         for band in RISK_ORDER + ["GREEN", "YELLOW", "ORANGE", "RED"]},
        "band_labels": BAND_LABELS,
        "band_advice": BAND_ADVICE,
        "stress_labels": STRESS_LABELS,
        "alert_gateway": alert_engine.gateway_status(),
    }


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


@app.get("/districts", tags=["districts"], dependencies=[Depends(require_access)])
def districts(replay: str = REPLAY_QUERY):
    """Every district, most urgent first (IMD code, then priority score)."""
    snap = current(replay)
    ranked = sorted(snap["results"].items(),
                    key=lambda kv: (code_index(kv[1]["imd"]["code"]), kv[1]["priority"]), reverse=True)
    return {**_source(snap), "districts": [_summary(n, m) for n, m in ranked]}


@app.get("/districts/{name}", tags=["districts"], dependencies=[Depends(require_access)])
def district(name: str, replay: str = REPLAY_QUERY):
    """Full detail for one district: current conditions, 5-day forecast, IMD code, actions."""
    snap = current(replay)
    district_name, m = _find(snap["results"], name)
    alert = next((a for a in snap["alerts"] if a["district"] == district_name), None)
    return {**_source(snap), **_summary(district_name, m),
            "wind_ms": m["wind"], "solar_wm2": m["solar"], "heat_index_now": m["heat_index"],
            "feels_like_shade_now": m["stress_shade"], "normals_loaded": m.get("has_normals", False),
            "vulnerability": m["vulnerability"], "response_capacity": m["capacity"],
            "ground_temp": m.get("ground_temp"),
            "imd": m["imd"], "ensemble": m.get("ensemble"), "forecast": m["forecast"], "alert": alert,
            "suggested_actions": alert_engine.suggested_actions(m, alert),
            "census_note": m["demographic"].get("note")}


@app.get("/alerts", tags=["alerts"], dependencies=[Depends(require_access)])
def alerts(replay: str = REPLAY_QUERY):
    """Current WATCH / WARNING list (IMD heat-wave criteria, confirmed across forecast updates)."""
    snap = current(replay)
    return {**_source(snap), "alerts": snap["alerts"]}


@app.get("/alerts/log", tags=["alerts"], dependencies=[Depends(require_admin)])
def alert_log(limit: int = Query(default=50, ge=1, le=500)):
    """Alerts that were sent or logged, newest first. Contains officer names – protect with HEAT_API_KEY."""
    return alert_engine.read_log(limit)


@app.post("/refresh", tags=["alerts"], dependencies=[Depends(require_access)])
def refresh():
    """Download fresh weather now and re-check alerts (normally done every hour)."""
    refresh_live(force=True)
    with _lock:
        return _source(_snapshots[None])


@app.get("/geojson", tags=["map"])
def geojson():
    """District boundaries, for drawing the map in a web frontend (e.g. Leaflet)."""
    return FileResponse(MAP_FILE, media_type="application/geo+json")


if WEB_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="dashboard")

    @app.get("/app", include_in_schema=False)
    def dashboard_redirect():
        return RedirectResponse("/app/")


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HEAT_API_HOST", "127.0.0.1")
    port = int(os.environ.get("HEAT_API_PORT") or os.environ.get("PORT") or "8000")
    shown = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"\n  Web dashboard:  http://{shown}:{port}/app/\n  API docs:       http://{shown}:{port}/docs\n")
    # Behind a host's HTTPS proxy, trust its X-Forwarded-Proto so cookies are marked Secure.
    trust_proxy = os.environ.get("HEAT_TRUST_PROXY") == "1"
    uvicorn.run(app, host=host, port=port, proxy_headers=True,
                forwarded_allow_ips="*" if trust_proxy else "127.0.0.1")
