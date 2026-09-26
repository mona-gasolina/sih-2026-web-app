"""
Persistent, confidence-based alerting + SMS/WhatsApp dispatch.

PDF: "Triggers alerts only when high-risk predictions remain consistent
across forecast updates, which prevents premature warnings."

Rule (prototype):
  • A district is "at risk" in a forecast update if its 5-day forecast meets
    the IMD heat-wave criteria at YELLOW or above (see heatwave.py). The
    UTCI thermal-stress band is NOT used as a trigger: normal summer days in
    Tamil Nadu already reach "extreme heat stress", so it would warn daily.
  • 1st update at risk  → WATCH   (not yet confirmed, nothing is sent)
  • ≥2 consecutive updates at risk → WARNING (confirmed) → dispatched once
    to the city administrators assigned to that district.
  • One update not at risk resets the streak.

Dispatch: Twilio REST API when these environment variables are set –
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM (SMS number) and/or
  TWILIO_WHATSAPP_FROM (e.g. whatsapp:+14155238886).
Without them, every alert is still written to data/alert_log.csv so the
flow can be demonstrated.
"""
import base64
import csv
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime

from config import ALERT_STATE_FILE, ALERT_LOG_FILE, DATA_DIR
from heatwave import code_index

CONFIRM_UPDATES = 2


def _load_state():
    try:
        return json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ALERT_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def evaluate(zone_metrics, weather_info):
    """
    zone_metrics: {district: metrics dict with "forecast" list}
    weather_info: {"source", "fetched_at", "fresh"}
    Returns (alerts list sorted by severity, newly confirmed list).
    Only real, freshly fetched forecasts advance the persistence counter.
    """
    persist = weather_info.get("source", "").startswith("Open-Meteo")
    state = _load_state() if persist else {}
    fetched_at = weather_info.get("fetched_at", 0)
    alerts, newly_confirmed = [], []

    for name, m in zone_metrics.items():
        imd = m.get("imd") or {}
        risky = imd.get("code", "GREEN") != "GREEN"
        entry = state.get(name, {"streak": 0, "last_update": 0, "dispatched": False})

        if persist and weather_info.get("fresh") and entry.get("last_update") != fetched_at:
            entry["streak"] = entry.get("streak", 0) + 1 if risky else 0
            entry["last_update"] = fetched_at
            if not risky:
                entry["dispatched"] = False
        streak = entry.get("streak", 0) if persist else (1 if risky else 0)
        if persist and risky and streak == 0:
            streak = 1          # first time we see it (e.g. loaded from cache)

        if risky:
            level = "WARNING" if streak >= CONFIRM_UPDATES else "WATCH"
            peak = imd["peak_day"]
            alert = {
                "district": name,
                "level": level,
                "colour": imd["code"],
                "risk": f"IMD {imd['code']} – {imd['label']}",
                "day": imd["first_day"],
                "tmax": peak["temp_max"],
                "departure": peak.get("departure"),
                "stress": peak["stress"],
                "model": peak["model"],
                "hours_danger": peak["hours_danger"],
                "score": m.get("risk_score", 0),
                "streak": streak,
                "confidence": (
                    f"Confirmed in {streak} consecutive forecast updates"
                    if level == "WARNING" else
                    "Seen in 1 forecast update – waiting for confirmation"
                ),
            }
            alerts.append(alert)
            if level == "WARNING" and persist and not entry.get("dispatched"):
                newly_confirmed.append(alert)
                entry["dispatched"] = True
        state[name] = entry

    if persist:
        _save_state(state)
    alerts.sort(key=lambda a: (a["level"] != "WARNING", -code_index(a["colour"]), -a["score"]))
    return alerts, newly_confirmed


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def gateway_status():
    sid, token = os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN")
    channels = []
    if sid and token and os.environ.get("TWILIO_FROM"):
        channels.append("SMS")
    if sid and token and os.environ.get("TWILIO_WHATSAPP_FROM"):
        channels.append("WhatsApp")
    return channels


def compose_message(alert, actions):
    first_action = actions[0] if actions else ""
    if alert.get("tmax") is not None:
        dep = alert.get("departure")
        dep_text = f" ({dep:+.1f}°C vs normal)" if dep is not None else ""
        what = f"{alert['risk']} from {alert['day']}. Max {alert['tmax']:.0f}°C{dep_text}"
    else:
        what = f"{alert['risk']} heat stress on {alert['day']}"
    return (
        f"HEAT {alert['level']} – {alert['district']}: {what}. Peak {alert['model']} "
        f"{alert['stress']:.0f}°C in sun, {alert['hours_danger']} h in danger range. "
        f"{first_action} – Heat Intelligence"
    )


def _mask(number):
    if not number:
        return ""
    return "•" * max(0, len(number) - 4) + number[-4:]


def _twilio_send(to, body, whatsapp=False):
    sid, token = os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]
    sender = os.environ["TWILIO_WHATSAPP_FROM" if whatsapp else "TWILIO_FROM"]
    if whatsapp and not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"
    data = urllib.parse.urlencode({"To": to, "From": sender, "Body": body}).encode()
    request = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data,
    )
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    request.add_header("Authorization", f"Basic {auth}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status


def dispatch(alert, recipients, actions):
    """
    recipients: list of user dicts (city admins) with "mobile".
    Returns list of (recipient label, channel, status) and appends to the log.
    """
    body = compose_message(alert, actions)
    channels = gateway_status()
    results = []
    targets = [r for r in recipients if r.get("mobile")]
    if not targets:
        results.append(("No officer with a mobile number is assigned", "—", "LOGGED ONLY"))
    for r in targets:
        label = f"{r.get('full_name') or r['username']} ({_mask(r['mobile'])})"
        if not channels:
            results.append((label, "SMS", "LOGGED – gateway not configured"))
            continue
        for channel in channels:
            try:
                _twilio_send(r["mobile"], body, whatsapp=(channel == "WhatsApp"))
                results.append((label, channel, "SENT"))
            except Exception as exc:
                results.append((label, channel, f"FAILED: {exc}"))
    _log(alert, body, results)
    return results


def _log(alert, body, results):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        new = not ALERT_LOG_FILE.exists()
        with open(ALERT_LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if new:
                writer.writerow(["timestamp", "district", "level", "risk", "recipient", "channel", "status", "message"])
            for label, channel, status in results:
                writer.writerow([datetime.now().isoformat(timespec="seconds"), alert["district"],
                                 alert["level"], alert["risk"], label, channel, status, body])
    except Exception:
        pass


def read_log(limit=50):
    try:
        with open(ALERT_LOG_FILE, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return rows[-limit:][::-1]
    except Exception:
        return []
