"""
Human thermal stress engine.

Primary model: UTCI (Universal Thermal Climate Index) from pythermalcomfort,
using air temperature, humidity, wind and solar radiation.

Fallback (if pythermalcomfort cannot be installed, e.g. on a brand-new Python
version where numba has no wheels yet): the NOAA/NWS Heat Index (Rothfusz
regression) – the same family of index IMD uses for its heat-index product.
The fallback is labelled in the UI so nobody mistakes it for UTCI.

Scoring (prototype, rule-based – documented so it can be reviewed).
Each index is mapped onto 0-100 using ITS OWN published category boundaries:
                      25          50               75             95
  UTCI (°C)      26 moderate  32 strong     38 very strong   46 extreme
  Heat index(°C) 26.7 caution 32.2 ext.caution 39.4 danger  51.7 extreme danger
                 (current NWS chart: 80 / 90 / 103 / 125 °F)
  thermal score = 75 % peak-stress score + 25 % exposure-duration score
      duration = hours in the day at/above the "75" level (UTCI 38 / HI 39.4);
      6 hours → 100. This separates a short afternoon spike from a long,
      dangerous exposure (PDF: heat exposure duration modelling).

UTCI is computed for a person standing in full sun (the worst case). A shade
value (no solar gain) is reported alongside it. The scores rank human heat
stress; whether a day is a heat wave – and so whether to warn – is decided
by heatwave.py (IMD criteria).

Cold: UTCI also covers cold stress (Bröde et al. 2012 categories below 9 °C),
so cold nights in the Nilgiris are labelled correctly. Cold-wave warnings are
out of scope for this heat-wave prototype (see README, future scope).
"""
import math

from config import RISK_ORDER

try:
    from pythermalcomfort.models import utci as _utci_model
    PYTHERMALCOMFORT_AVAILABLE = True
except Exception:  # ImportError, numba errors on unsupported Python, …
    _utci_model = None
    PYTHERMALCOMFORT_AVAILABLE = False

try:
    from pythermalcomfort.models import solar_gain as _solar_gain
except Exception:
    _solar_gain = None

DURATION_FULL_HOURS = 6.0
UTCI = "UTCI"
HEAT_INDEX = "Heat index"

SCALES = {
    UTCI: {
        "points": [(9.0, 0.0), (26.0, 25.0), (32.0, 50.0), (38.0, 75.0), (46.0, 95.0), (50.0, 100.0)],
        "danger": 38.0,
        "categories": [(46.0, "Extreme heat stress"), (38.0, "Very strong heat stress"),
                       (32.0, "Strong heat stress"), (26.0, "Moderate heat stress"),
                       (9.0, "No thermal stress"), (0.0, "Slight cold stress"),
                       (-13.0, "Moderate cold stress"), (-27.0, "Strong cold stress"),
                       (-40.0, "Very strong cold stress"), (-999, "Extreme cold stress")],
    },
    HEAT_INDEX: {
        "points": [(20.0, 0.0), (26.7, 25.0), (32.2, 50.0), (39.4, 75.0), (51.7, 95.0), (57.0, 100.0)],
        "danger": 39.4,
        "categories": [(51.7, "Extreme danger"), (39.4, "Danger"), (32.2, "Extreme caution"),
                       (26.7, "Caution"), (-999, "No heat concern")],
    },
}


def engine_name():
    return "UTCI (pythermalcomfort)" if PYTHERMALCOMFORT_AVAILABLE else "Heat index (fallback – install pythermalcomfort for UTCI)"


def stress_category(value, model=UTCI):
    if value is None:
        return "—"
    for threshold, name in SCALES.get(model, SCALES[UTCI])["categories"]:
        if value >= threshold:
            return name
    return "—"


# ---------------------------------------------------------------------------
# Published "feels like" indices (no dependencies)
# ---------------------------------------------------------------------------
def heat_index_c(temp_c, rh):
    """NOAA / NWS Heat Index (Rothfusz regression with NWS adjustments)."""
    t = temp_c * 9 / 5 + 32
    rh = max(0.0, min(100.0, rh))
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if (simple + t) / 2 < 80:
        hi = simple
    else:
        hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh
              - 0.22475541 * t * rh - 0.00683783 * t * t
              - 0.05481717 * rh * rh + 0.00122874 * t * t * rh
              + 0.00085282 * t * rh * rh - 0.00000199 * t * t * rh * rh)
        if rh < 13 and 80 <= t <= 112:
            hi -= ((13 - rh) / 4) * math.sqrt((17 - abs(t - 95)) / 17)
        elif rh > 85 and 80 <= t <= 87:
            hi += ((rh - 85) / 10) * ((87 - t) / 5)
    return (hi - 32) * 5 / 9


# ---------------------------------------------------------------------------
# UTCI
# ---------------------------------------------------------------------------
_mrt_cache = {}


def _mean_radiant_temperature(tdb, solar):
    """Prototype MRT: air temperature + solar gain for a standing person."""
    if _solar_gain is None or solar <= 5:
        return tdb
    key = int(round(solar / 25.0)) * 25
    if key not in _mrt_cache:
        try:
            result = _solar_gain(
                sol_altitude=60.0, sharp=0.0, sol_radiation_dir=float(key),
                sol_transmittance=1.0, f_svv=0.5, f_bes=0.5, asw=0.7, posture="standing",
            )
            delta = getattr(result, "delta_mrt", None)
            if delta is None and isinstance(result, dict):
                delta = result.get("delta_mrt")
            _mrt_cache[key] = float(delta or 0.0)
        except Exception:
            _mrt_cache[key] = 0.0
    return tdb + _mrt_cache[key]


def _utci(tdb, tr, wind, rh):
    result = _utci_model(
        tdb=float(tdb), tr=float(tr), v=min(max(float(wind), 0.5), 17.0),
        rh=float(rh), units="SI", limit_inputs=True,
    )
    value = getattr(result, "utci", result)
    if isinstance(value, dict):
        value = value.get("utci")
    value = float(value)
    return None if math.isnan(value) else value


def stress_value(tdb, rh, wind, solar):
    """Return (stress °C, model name). Never returns None."""
    if PYTHERMALCOMFORT_AVAILABLE:
        try:
            tr = _mean_radiant_temperature(float(tdb), float(solar))
            tr = min(max(tr, tdb - 30.0), tdb + 70.0)
            value = _utci(tdb, tr, wind, rh)
            if value is not None:
                return round(value, 1), UTCI
        except Exception:
            pass
    return round(heat_index_c(float(tdb), float(rh)), 1), HEAT_INDEX


# ---------------------------------------------------------------------------
# Scores and bands
# ---------------------------------------------------------------------------
def score_from_stress(value, model=UTCI):
    points = SCALES.get(model, SCALES[UTCI])["points"]
    if value <= points[0][0]:
        return 0.0
    if value >= points[-1][0]:
        return 100.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if x1 <= value <= x2:
            return y1 + (y2 - y1) * (value - x1) / (x2 - x1)
    return 100.0


def duration_score(hours_danger):
    return max(0.0, min(100.0, hours_danger / DURATION_FULL_HOURS * 100.0))


def combined_thermal_score(peak_stress, hours_danger, model=UTCI):
    return round(0.75 * score_from_stress(peak_stress, model) + 0.25 * duration_score(hours_danger), 1)


def risk_band(score):
    if score < 25:
        return "VERY LOW"
    if score < 45:
        return "LOW"
    if score < 60:
        return "MODERATE"
    if score < 75:
        return "HIGH"
    return "EXTREME"


def band_index(band):
    return RISK_ORDER.index(band) if band in RISK_ORDER else -1


# ---------------------------------------------------------------------------
# Demographic vulnerability / relative risk
# ---------------------------------------------------------------------------
def vulnerability_score(demographic):
    """
    Prototype vulnerability: log-scaled population exposure.
    Returns None when no Census population is available for this area.
    Ready to be replaced by elderly / outdoor-worker / NFHS health indicators.
    """
    population = float(demographic.get("population", 0) or 0)
    if population <= 0:
        return None
    return max(0.0, min(100.0, 35.0 + 15.0 * math.log10(population / 500_000 + 1)))


def relative_risk_score(thermal_score, demographic):
    """70 % thermal stress + 30 % demographic exposure (state-typical value if unknown)."""
    vuln = vulnerability_score(demographic)
    if vuln is None:
        vuln = 50.0
    return round(0.70 * thermal_score + 0.30 * vuln, 1)


# ---------------------------------------------------------------------------
# Daily aggregation from hourly forecast
# ---------------------------------------------------------------------------
def summarise_day(hours):
    """
    hours: list of dicts with temperature, humidity, wind (m/s), solar (W/m²).
    Returns peak stress, exposure hours and the combined score/band.
    """
    if not hours:
        return None
    results = [stress_value(h["temperature"], h["humidity"], h["wind"], h["solar"]) for h in hours]
    model = results[0][1]
    stresses = [v for v, _ in results]
    peak = max(stresses)
    peak_i = stresses.index(peak)
    danger = SCALES[model]["danger"]
    hours_danger = sum(1 for v in stresses if v >= danger)
    score = combined_thermal_score(peak, hours_danger, model)
    temps = [h["temperature"] for h in hours]
    shade = max(stress_value(h["temperature"], h["humidity"], h["wind"], 0.0)[0] for h in hours)
    return {
        "stress": peak,
        "stress_shade": shade,
        "model": model,
        "category": stress_category(peak, model),
        "hours_danger": hours_danger,
        "danger_threshold": danger,
        "peak_time": hours[peak_i].get("time", "")[11:16],
        "thermal_score": score,
        "risk": risk_band(score),
        "temp_max": max(temps),
        "temp_min": min(temps),
        "humidity_at_peak": hours[peak_i]["humidity"],
        "heat_index_max": round(max(heat_index_c(h["temperature"], h["humidity"]) for h in hours), 1),
        "hourly_stress": stresses,
    }


def calculate_current(current, today_hours_danger=0):
    """Current conditions: instantaneous stress plus today's exposure hours."""
    value, model = stress_value(current["temperature"], current["humidity"],
                                current["wind"], current["solar"])
    score = combined_thermal_score(value, today_hours_danger, model)
    return {
        "stress": value,
        "stress_shade": stress_value(current["temperature"], current["humidity"], current["wind"], 0.0)[0],
        "model": model,
        "category": stress_category(value, model),
        "heat_index": round(heat_index_c(current["temperature"], current["humidity"]), 1),
        "thermal_score": score,
        "risk": risk_band(score),
    }
