"""
IMD heat-wave criteria – decides WHEN to warn.

UTCI (thermal.py) says how stressful the heat is for a person outdoors, but it
does not say whether a day is unusually hot: an ordinary May afternoon in
Madurai already scores "extreme heat stress". Warnings therefore follow the
India Meteorological Department (IMD) heat-wave definition, which compares
the day's maximum temperature with the local normal for that date.

Per day (IMD criteria):
  A heat wave is considered only once Tmax reaches
      40 °C plains  •  37 °C coastal  •  30 °C hills
  and then
      departure from normal 4.5 – 6.4 °C  → HEAT WAVE
      departure from normal  > 6.4 °C     → SEVERE HEAT WAVE
  or, whatever the normal,
      Tmax ≥ 45 °C → HEAT WAVE     Tmax ≥ 47 °C → SEVERE HEAT WAVE

District colour code over the forecast (after IMD's colour-coded warnings,
adapted to a 5-day district forecast):
  YELLOW  heat wave on 2 consecutive days
  ORANGE  severe heat wave on 2 consecutive days, or heat wave on 4+ days in a row
  RED     severe heat wave on 3+ consecutive days
  GREEN   otherwise (a single heat-wave day is shown but does not raise a colour)

Prototype limits (documented so they can be reviewed):
  • One weather point per district instead of IMD stations; IMD also needs
    the criteria at 2+ stations of a sub-division.
  • Normals are built from Open-Meteo's archive of past forecasts (same model
    family as the live forecast, so departures are not skewed by model bias),
    over a short 4-year window – see weather.get_tmax_normals().
"""
from datetime import datetime

# Terrain decides the minimum Tmax. "Coastal" = district has a coastline.
COASTAL = {
    "thiruvallur", "chennai", "chengalpattu", "viluppuram", "cuddalore", "nagapattinam",
    "mayiladuthurai", "thiruvarur", "thanjavur", "pudukkottai", "ramanathapuram",
    "thoothukkudi", "thoothukudi", "tirunelveli", "kanyakumari",
}
HILLS = {"nilgiris", "the nilgiris"}

MIN_TMAX = {"plains": 40.0, "coastal": 37.0, "hills": 30.0}
DEPARTURE_HW = 4.5
DEPARTURE_SEVERE = 6.5          # "more than 6.4 °C"
ABSOLUTE_HW = 45.0
ABSOLUTE_SEVERE = 47.0

NONE, HEAT_WAVE, SEVERE = "NONE", "HEAT WAVE", "SEVERE HEAT WAVE"
CODES = ["GREEN", "YELLOW", "ORANGE", "RED"]
CODE_LABELS = {
    "GREEN": "No heat wave",
    "YELLOW": "Heat wave",
    "ORANGE": "Severe heat wave",
    "RED": "Extreme heat – prolonged severe heat wave",
}


def terrain(district):
    name = district.lower().strip()
    if name in HILLS:
        return "hills"
    if name in COASTAL:
        return "coastal"
    return "plains"


def _normal_index(date_str):
    """Day index 0-364 in a non-leap calendar; 29 Feb uses 28 Feb."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    day = 28 if (d.month, d.day) == (2, 29) else d.day
    return datetime(2001, d.month, day).timetuple().tm_yday - 1


def normal_for(normals, date_str):
    """normals: list of 365 daily Tmax normals for one district (or None)."""
    if not normals or len(normals) != 365:
        return None
    try:
        return normals[_normal_index(date_str)]
    except ValueError:
        return None


def classify_day(tmax, normal, kind="plains"):
    """Returns (NONE | HEAT WAVE | SEVERE HEAT WAVE, departure or None)."""
    departure = None if normal is None else round(tmax - normal, 1)
    level = NONE
    if tmax >= ABSOLUTE_SEVERE:
        level = SEVERE
    elif tmax >= ABSOLUTE_HW:
        level = HEAT_WAVE
    if departure is not None and tmax >= MIN_TMAX[kind]:
        if departure >= DEPARTURE_SEVERE:
            level = SEVERE
        elif departure >= DEPARTURE_HW and level == NONE:
            level = HEAT_WAVE
    return level, departure


def _longest_run(flags):
    run = best = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def district_code(forecast):
    """forecast: list of day dicts with "heatwave". Returns the zone's IMD summary."""
    levels = [d.get("heatwave", NONE) for d in forecast]
    run_any = _longest_run([lv != NONE for lv in levels])
    run_severe = _longest_run([lv == SEVERE for lv in levels])
    if run_severe >= 3:
        code = "RED"
    elif run_severe >= 2 or run_any >= 4:
        code = "ORANGE"
    elif run_any >= 2:
        code = "YELLOW"
    else:
        code = "GREEN"

    hw_days = [d for d in forecast if d.get("heatwave", NONE) != NONE]
    first = hw_days[0] if hw_days else None
    peak = max(hw_days, key=lambda d: d["temp_max"]) if hw_days else None
    if code != "GREEN":
        reason = f"{len(hw_days)} heat-wave day{'s' if len(hw_days) != 1 else ''} forecast, {run_any} in a row"
    elif hw_days:
        reason = "1 heat-wave day forecast – IMD needs 2 in a row"
    else:
        reason = "Max temperatures within the normal range"
    return {
        "code": code,
        "label": CODE_LABELS[code],
        "hw_days": len(hw_days),
        "severe_days": sum(1 for lv in levels if lv == SEVERE),
        "longest_run": run_any,
        "first_day": first["date_text"] if first else "",
        "peak_day": peak,
        "reason": reason,
    }


def code_index(code):
    return CODES.index(code) if code in CODES else 0
