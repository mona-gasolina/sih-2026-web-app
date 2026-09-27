"""
Turns raw weather + Census data into the metrics the dashboard shows.
Runs inside the background weather thread, so the UI never freezes.
"""
from datetime import datetime

import heatwave
from thermal import (
    summarise_day, calculate_current, relative_risk_score, vulnerability_score,
    duration_score, band_index,
)

HIGH_BANDS = ("HIGH", "EXTREME")
DEFAULT_CAPACITY = 50.0


def _date_text(date_str, index, relative=True):
    if relative and index == 0:
        return "Today"
    if relative and index == 1:
        return "Tomorrow"
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a %d %b")
    except Exception:
        return f"Day {index + 1}"


def _longest_run(bands):
    run = best = 0
    for band in bands:
        run = run + 1 if band in HIGH_BANDS else 0
        best = max(best, run)
    return best


def compute_zone(name, data, demographic, capacity=None, normals=None, replay=None, bias=None):
    """
    data: normalised weather for one district (weather.normalize output)
    normals: 365 daily Tmax normals for the district (weather.get_tmax_normals)
    replay: start date (YYYY-MM-DD) when replaying archived weather, else None
    bias: {model: [365 offsets]} for the model-agreement check (weather.get_model_bias)
    Returns the full metrics dict for that district.
    """
    kind = heatwave.terrain(name)
    lat, lon = data.get("lat"), data.get("lon")
    today = replay or datetime.now().strftime("%Y-%m-%d")
    days = [d for d in data["days"] if d["date"] >= today][:5] or data["days"][:5]

    forecast = []
    for i, day in enumerate(days):
        summary = summarise_day(day["hours"], lat, lon)
        if summary is None:
            continue
        summary.update({"date": day["date"], "date_text": _date_text(day["date"], i, relative=not replay)})
        summary.pop("hourly_stress", None)
        normal = heatwave.normal_for(normals, day["date"])
        level, departure = heatwave.classify_day(summary["temp_max"], normal, kind)
        summary.update({"normal_max": normal, "departure": departure, "heatwave": level})
        forecast.append(summary)

    today_summary = forecast[0] if forecast else None
    current = data["current"]
    now = calculate_current(current, today_summary["hours_danger"] if today_summary else 0, lat, lon)

    thermal_score = today_summary["thermal_score"] if today_summary else now["thermal_score"]
    risk = today_summary["risk"] if today_summary else now["risk"]
    risk_score = relative_risk_score(thermal_score, demographic)

    bands = [f["risk"] for f in forecast]
    ranked = [b for b in bands if band_index(b) >= 0]
    peak_band = max(ranked, key=band_index) if ranked else "—"
    next3 = forecast[:3]
    max_hours = max((f["hours_danger"] for f in next3), default=0)
    peak_next3 = max((relative_risk_score(f["thermal_score"], demographic) for f in next3), default=risk_score)

    cap = DEFAULT_CAPACITY if capacity is None else capacity
    priority = round(0.60 * peak_next3 + 0.25 * duration_score(max_hours) + 0.15 * (100 - cap), 1)

    return {
        "loaded": True,
        "temperature": current["temperature"],
        "humidity": current["humidity"],
        "wind": current["wind"],
        "solar": current["solar"],
        "cloud": current.get("cloud"),
        "ground_temp": current.get("ground_temp"),
        "observed_at": current.get("time", ""),
        "stress": now["stress"],
        "stress_shade": now["stress_shade"],
        "stress_model": now["model"],
        "stress_category": now["category"],
        "heat_index": now["heat_index"],
        "today_peak_stress": today_summary["stress"] if today_summary else now["stress"],
        "today_hours_danger": today_summary["hours_danger"] if today_summary else 0,
        "thermal_score": thermal_score,
        "risk": risk,
        "risk_score": risk_score,
        "vulnerability": vulnerability_score(demographic),
        "forecast": forecast,
        "days_high": sum(1 for b in bands if b in HIGH_BANDS),
        "longest_high_run": _longest_run(bands),
        "peak_band": peak_band,
        "priority": priority,
        "capacity": capacity,
        "demographic": demographic,
        "terrain": kind,
        "has_normals": bool(normals),
        "imd": heatwave.district_code(forecast),
        "ensemble": heatwave.ensemble_check(forecast, data.get("model_tmax"), normals, bias, kind),
    }


def placeholder_metrics(demographic):
    """Shown while weather is loading – grey on the map, no invented numbers."""
    return {
        "loaded": False, "temperature": 0.0, "humidity": 0.0, "wind": 0.0, "solar": 0.0,
        "stress": 0.0, "stress_shade": 0.0, "stress_model": "—", "stress_category": "—", "heat_index": 0.0,
        "today_peak_stress": 0.0, "today_hours_danger": 0, "thermal_score": 0.0,
        "risk": "LOADING", "risk_score": 0.0, "vulnerability": vulnerability_score(demographic),
        "forecast": [], "days_high": 0, "longest_high_run": 0, "peak_band": "—",
        "priority": 0.0, "capacity": None, "demographic": demographic,
        "terrain": "", "has_normals": False, "imd": heatwave.district_code([]),
        "ensemble": {"codes": {}, "tmax": {}, "agree": 0, "total": 0},
    }
