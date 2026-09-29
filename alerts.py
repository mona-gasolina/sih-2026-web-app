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
  • An "update" only counts if it is at least MIN_UPDATE_GAP_HOURS after the
    previous one: the app re-downloads hourly, but the weather models behind
    Open-Meteo publish a new run about every 6 h, so two downloads an hour
    apart are usually the same forecast and would not be a real confirmation.
  • One update not at risk resets the streak; so does a gap longer than
    MAX_UPDATE_GAP_HOURS (the updates were not consecutive).
  • Second opinion: the same IMD test is run on three independent weather
    models (ECMWF, GFS, ICON, each bias-corrected). At least
    ENSEMBLE_MIN_AGREE of them must back the main forecast; otherwise the
    district stays on WATCH ("low confidence") and nothing is sent.
  • No repeats: a district is not messaged again within RESEND_HOURS for the
    same or a lower colour, even if the heat wave flickers off and on. A
    worse colour (YELLOW → ORANGE → RED) is sent straight away as an upgrade.
  • Replay (archived weather) shows the levels but never sends or stores anything.

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

from config import (
    ALERT_STATE_FILE, ALERT_LOG_FILE, DATA_DIR, ENSEMBLE_MIN_AGREE, atomic_write_text, file_lock,
    band_label,
)
from heatwave import code_index

CONFIRM_UPDATES = 2
MIN_UPDATE_GAP_HOURS = 6
MAX_UPDATE_GAP_HOURS = 36
RESEND_HOURS = 48


def _load_state():
    try:
        return json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state):
    try:
        atomic_write_text(ALERT_STATE_FILE, json.dumps(state, indent=2))
    except Exception:
        pass


def evaluate(zone_metrics, weather_info):
    """Update WATCH/WARNING for every district (see _evaluate).

    The desktop app and the web API may both run this at the same moment. The
    lock makes read-decide-save one step, so the second one sees "already sent"
    and a warning goes out exactly once."""
    if weather_info.get("source", "").startswith("Open-Meteo"):
        with file_lock(ALERT_STATE_FILE):
            return _evaluate(zone_metrics, weather_info)
    return _evaluate(zone_metrics, weather_info)


def _evaluate(zone_metrics, weather_info):
    """
    zone_metrics: {district: metrics dict with "forecast" list}
    weather_info: {"source", "fetched_at", "fresh"}
    Returns (alerts list sorted by severity, newly confirmed list).
    Only real, freshly fetched forecasts advance the persistence counter.
    """
    replay = bool(weather_info.get("replay"))
    persist = weather_info.get("source", "").startswith("Open-Meteo")
    state = _load_state() if persist else {}
    fetched_at = weather_info.get("fetched_at", 0)
    alerts, newly_confirmed = [], []

    for name, m in zone_metrics.items():
        imd = m.get("imd") or {}
        risky = imd.get("code", "GREEN") != "GREEN"
        ens = m.get("ensemble") or {}
        have_models = ens.get("total", 0) >= 2
        agreed = ens.get("agree", 0) >= ENSEMBLE_MIN_AGREE if have_models else True
        alertable = risky and agreed
        entry = state.get(name, {"streak": 0, "last_update": 0, "dispatched": False})

        if persist and weather_info.get("fresh") and entry.get("last_update") != fetched_at:
            gap_hours = (fetched_at - entry.get("last_update", 0)) / 3600.0
            if not alertable:
                entry.update(streak=0, last_update=fetched_at, dispatched=False)
            elif entry.get("streak", 0) == 0 or gap_hours > MAX_UPDATE_GAP_HOURS:
                entry.update(streak=1, last_update=fetched_at, dispatched=False)
            elif gap_hours >= MIN_UPDATE_GAP_HOURS:
                entry.update(streak=entry["streak"] + 1, last_update=fetched_at)
            # else: same model run downloaded again – not a new update
        streak = entry.get("streak", 0) if persist else (1 if alertable else 0)
        if persist and alertable and streak == 0:
            streak = 1          # first time we see it (e.g. loaded from cache)
        models_text = (f"backed by {ens['agree']} of {ens['total']} other weather models" if have_models
                       else "other weather models unavailable – main forecast only")

        if risky:
            if not agreed:
                level = "WATCH"
                confidence = (f"Low confidence – none of the {ens['total']} other weather models "
                              "show this heat wave, so it isn't escalated")
            elif replay:
                level, confidence = "WARNING", "Replay of archived weather – shown as confirmed, nothing is sent"
            elif streak >= CONFIRM_UPDATES:
                level = "WARNING"
                confidence = (f"Confirmed in {streak} consecutive forecast updates "
                              f"(≥ {MIN_UPDATE_GAP_HOURS} h apart); {models_text}")
            else:
                level = "WATCH"
                confidence = (f"Seen in 1 forecast update ({models_text}) – confirmed if the next "
                              f"update (≥ {MIN_UPDATE_GAP_HOURS} h later) agrees")
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
                "models": f"{ens.get('agree', 0)}/{ens.get('total', 0)}" if have_models else "",
                "confidence": confidence,
            }
            alerts.append(alert)
            if level == "WARNING" and persist and _should_send(entry, imd["code"], fetched_at):
                if entry.get("dispatched"):
                    alert["upgrade"] = True
                newly_confirmed.append(alert)
                entry.update(dispatched=True, sent_code=imd["code"], sent_at=fetched_at)
        state[name] = entry

    if persist:
        _save_state(state)
    alerts.sort(key=lambda a: (a["level"] != "WARNING", -code_index(a["colour"]), -a["score"]))
    return alerts, newly_confirmed


def _should_send(entry, code, now):
    """Send once per heat wave; again only if it gets worse, or after RESEND_HOURS."""
    worse = code_index(code) > code_index(entry.get("sent_code", "GREEN"))
    if entry.get("dispatched"):
        return worse                                   # already told: only upgrades
    recent = now - entry.get("sent_at", 0) < RESEND_HOURS * 3600
    return worse or not recent                         # flicker off/on within 48 h: stay quiet


HIGH_STRESS_BANDS = ("HIGH", "EXTREME")


def suggested_actions(m, alert=None):
    """
    Warning level from the IMD heat-wave code; day-to-day advice from UTCI stress.
    alert: this district's entry from evaluate(). An ORANGE / RED heat wave gets
    the full Heat Action Plan only once it is a confirmed WARNING; while it is a
    WATCH (one forecast update, or the other models disagree) officers prepare.
    """
    code = m.get("imd", {}).get("code", "GREEN")
    if code in ("RED", "ORANGE") and (alert or {}).get("level") != "WARNING":
        return [
            "Heat wave forecast but not yet confirmed: get the Heat Action Plan ready.",
            "Prepare cooling centres and drinking-water points.",
            "Ask employers of outdoor workers to plan shade and rest breaks.",
            "Check again after the next forecast update.",
        ]
    if code in ("RED", "ORANGE"):
        return [
            "Activate the Heat Action Plan for this area.",
            "Open cooling centres and drinking-water points.",
            "Shift outdoor work away from 12 pm – 4 pm.",
            "Alert hospitals / PHCs; check on elderly people living alone.",
        ]
    if code == "YELLOW":
        return [
            "Issue a public heat advisory (SMS, radio, local TV).",
            "Prepare cooling centres and water points.",
            "Ask employers of outdoor workers to plan shade and rest breaks.",
        ]
    if m.get("peak_band") in HIGH_STRESS_BANDS:
        return [
            "No heat wave forecast, but outdoor heat stress is high: share hydration and shade guidance.",
            "Remind employers of outdoor workers about rest breaks in the afternoon.",
        ]
    return ["Routine monitoring – no action needed right now."]


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
    """Short SMS in plain words, e.g.
    HEAT WARNING, Madurai: red alert from Tue 30 Apr. Up to 44°C, 7°C above normal;
    feels like 48°C in the sun. Activate the Heat Action Plan. – Heat Intelligence"""
    first_action = actions[0] if actions else ""
    colour = alert.get("colour")
    if alert.get("tmax") is not None:
        dep = alert.get("departure")
        above = f", {dep:.0f}°C above normal" if dep is not None and dep > 0 else ""
        what = f"{colour.lower()} alert from {alert['day']}. Up to {alert['tmax']:.0f}°C{above}"
    else:
        what = f"{band_label(alert['risk']).lower()} {alert['day'].lower()}"
    heading = "HEAT WARNING UPDATE" if alert.get("upgrade") else f"HEAT {alert['level']}"
    return (f"{heading}, {alert['district']}: {what}; feels like {alert['stress']:.0f}°C in the sun. "
            f"{first_action} – Heat Intelligence")


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
        results.append(("No officer assigned", "", "Not sent"))
    for r in targets:
        label = f"{r.get('full_name') or r['username']} ({_mask(r['mobile'])})"
        if not channels:
            results.append((label, "SMS", "Not sent – SMS not set up"))
            continue
        for channel in channels:
            try:
                _twilio_send(r["mobile"], body, whatsapp=(channel == "WhatsApp"))
                results.append((label, channel, "Sent"))
            except Exception as exc:
                results.append((label, channel, f"Failed: {exc}"))
    _log(alert, body, results)
    return results


LOG_COLUMNS = ["timestamp", "district", "level", "code", "heat_from", "recipient", "channel", "status", "message"]


def _log(alert, body, results):
    """timestamp = when the alert was logged; heat_from = first forecast heat-wave day."""
    try:
        with file_lock(ALERT_LOG_FILE):
            _append_log(alert, body, results)
    except Exception:
        pass


def _append_log(alert, body, results):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if ALERT_LOG_FILE.exists():
        with open(ALERT_LOG_FILE, "r", encoding="utf-8") as f:
            header = f.readline().strip().split(",")
        if header != LOG_COLUMNS:          # older format: keep it, start a fresh log
            ALERT_LOG_FILE.replace(ALERT_LOG_FILE.with_name("alert_log_old.csv"))
    new = not ALERT_LOG_FILE.exists()
    with open(ALERT_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(LOG_COLUMNS)
        for label, channel, status in results:
            writer.writerow([datetime.now().isoformat(timespec="seconds"), alert["district"],
                             alert["level"], alert.get("colour", ""), alert.get("day", ""),
                             label, channel, status, body])


def read_log(limit=50):
    try:
        with open(ALERT_LOG_FILE, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if rows and "heat_from" not in rows[0]:
            return []                          # older format (before the heat-from column)
        return rows[-limit:][::-1]
    except Exception:
        return []
