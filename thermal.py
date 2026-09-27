"""
Human thermal stress engine.

Primary model: UTCI (Universal Thermal Climate Index) from pythermalcomfort,
using air temperature, humidity, wind and solar radiation.

Fallback (if pythermalcomfort cannot be installed, e.g. on a brand-new Python
version where numba has no wheels yet): the NOAA/NWS Heat Index (Rothfusz
regression) – the same family of index IMD uses for its heat-index product.
The fallback is labelled in the UI so nobody mistakes it for UTCI.

Scoring (rule-based – documented so it can be reviewed).
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
value (no direct sun) is reported alongside it. The scores rank human heat
stress; whether a day is a heat wave – and so whether to warn – is decided
by heatwave.py (IMD criteria).

Mean radiant temperature (MRT) – the "sun and hot ground" part of UTCI – is
computed hour by hour from the forecast radiation, following the method used
for the Copernicus ERA5-HEAT UTCI data set (Di Napoli et al. 2020, "Mean radiant
temperature from global-scale numerical weather prediction models",
Int J Biometeorol 64:1233–1245):
  • direct sun (direct normal irradiance) × the body's projected area at the
    real sun elevation for that district and hour,
  • diffuse sky light and sunlight reflected by the ground (albedo 0.2),
  • longwave heat from the sky (Brutsaert 1975 clear-sky emissivity, raised
    by cloud cover as in Crawford & Duchon 1999) and from the ground (model
    surface temperature – a sunlit ground at 50 °C radiates a lot of heat).
So clouds count twice: they cut direct sun (in the radiation forecast) and
they add longwave heat at night and on humid days.

Cold: UTCI also covers cold stress (Bröde et al. 2012 categories below 9 °C),
so cold nights in the Nilgiris are labelled correctly. Cold-wave warnings are
out of scope for this heat-wave prototype (see README, future scope).
"""
import math
from datetime import datetime

from config import RISK_ORDER

try:
    from pythermalcomfort.models import utci as _utci_model
    PYTHERMALCOMFORT_AVAILABLE = True
except Exception:  # ImportError, numba errors on unsupported Python, …
    _utci_model = None
    PYTHERMALCOMFORT_AVAILABLE = False

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
# Sun position and mean radiant temperature
# ---------------------------------------------------------------------------
SIGMA = 5.67e-8                 # Stefan–Boltzmann constant
IST_MERIDIAN = 82.5             # standard meridian of Indian Standard Time (°E)
ALBEDO = 0.2                    # typical ground reflectance (grass/soil/concrete mix)
GROUND_EMISSIVITY = 0.95
BODY_SW_ABSORPTION = 0.7        # clothed human, shortwave (Di Napoli et al. 2020)
BODY_EMISSIVITY = 0.97
F_A = 0.5                       # half the radiation comes from above, half from below


def solar_elevation(lat, lon, stamp, minutes_back=30):
    """
    Sun elevation (degrees) at a local IST time "YYYY-MM-DDTHH:MM". Open-Meteo
    radiation is the mean over the hour BEFORE the stamp, so the sun position
    is taken at the middle of that hour (minutes_back=30).
    """
    try:
        day_of_year = datetime.strptime(stamp[:10], "%Y-%m-%d").timetuple().tm_yday
        clock = int(stamp[11:13]) + int(stamp[14:16]) / 60.0 - minutes_back / 60.0
    except (ValueError, IndexError):
        return 0.0
    b = math.radians(360.0 / 365.0 * (day_of_year - 81))
    eq_time = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)       # minutes
    solar_time = clock + (4.0 * (lon - IST_MERIDIAN) + eq_time) / 60.0
    hour_angle = math.radians(15.0 * (solar_time - 12.0))
    decl = math.radians(23.44 * math.sin(math.radians(360.0 / 365.0 * (284 + day_of_year))))
    phi = math.radians(lat)
    sin_el = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))


def _sky_emissivity(tdb, rh, cloud_fraction):
    """Brutsaert (1975) clear sky, raised by cloud cover (Crawford & Duchon 1999)."""
    vapour_hpa = rh / 100.0 * 6.112 * math.exp(17.62 * tdb / (243.12 + tdb))      # Magnus formula
    clear = 1.24 * (vapour_hpa / (tdb + 273.15)) ** (1.0 / 7.0)
    c = max(0.0, min(1.0, cloud_fraction))
    return min(1.0, c + (1.0 - c) * clear)


def mean_radiant_temperature(hour, lat, lon, shade=False):
    """
    MRT (°C) for a standing person, from one forecast hour:
    hour = {temperature, humidity, solar (global), dni, diffuse, cloud (%), ground_temp, time}.
    shade=True removes the direct sun (a person under a tree or awning).
    Returns None if the radiation fields are missing (old cached data).
    """
    if "dni" not in hour:
        return None
    tdb = float(hour["temperature"])
    ground = float(hour.get("ground_temp", tdb) if hour.get("ground_temp") is not None else tdb)
    elevation = solar_elevation(lat, lon, hour.get("time", ""), hour.get("avg_minutes", 60) / 2.0)
    sun_up = elevation > 0.0

    long_down = _sky_emissivity(tdb, float(hour["humidity"]), float(hour.get("cloud", 0)) / 100.0) \
        * SIGMA * (tdb + 273.15) ** 4
    long_up = GROUND_EMISSIVITY * SIGMA * (ground + 273.15) ** 4
    diffuse = float(hour["diffuse"]) if sun_up else 0.0
    reflected = ALBEDO * float(hour["solar"]) if sun_up else 0.0
    direct = 0.0
    if sun_up and not shade:
        gamma = elevation
        projected_area = 0.308 * math.cos(math.radians(gamma * (0.998 - gamma * gamma / 50000.0)))
        direct = projected_area * float(hour["dni"])

    absorbed = F_A * (long_down + long_up) + BODY_SW_ABSORPTION / BODY_EMISSIVITY * (
        F_A * (diffuse + reflected) + direct)
    return (absorbed / SIGMA) ** 0.25 - 273.15


# ---------------------------------------------------------------------------
# UTCI
# ---------------------------------------------------------------------------
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


def stress_value(hour, lat=None, lon=None, shade=False):
    """
    Return (stress °C, model name) for one hour of weather. Never returns None.
    hour: dict with temperature, humidity, wind (m/s) and the radiation fields.
    """
    tdb, rh = float(hour["temperature"]), float(hour["humidity"])
    if PYTHERMALCOMFORT_AVAILABLE:
        try:
            tr = mean_radiant_temperature(hour, lat or 0.0, lon or 0.0, shade) if lat is not None else None
            if tr is None:
                tr = tdb                       # no radiation data: shade-like estimate
            tr = min(max(tr, tdb - 30.0), tdb + 70.0)     # UTCI validity range
            value = _utci(tdb, tr, hour["wind"], rh)
            if value is not None:
                return round(value, 1), UTCI
        except Exception:
            pass
    return round(heat_index_c(tdb, rh), 1), HEAT_INDEX


def stress_values(hours, lat=None, lon=None, shade=False):
    """
    Same as stress_value for a whole day at once (one UTCI call instead of 24 –
    the library checks its inputs on every call, which was most of the run time).
    Returns ([stress °C per hour], model name).
    """
    if PYTHERMALCOMFORT_AVAILABLE and hours:
        try:
            tdb = [float(h["temperature"]) for h in hours]
            rh = [float(h["humidity"]) for h in hours]
            trs = []
            for h, t in zip(hours, tdb):
                tr = mean_radiant_temperature(h, lat or 0.0, lon or 0.0, shade) if lat is not None else None
                trs.append(min(max(t if tr is None else tr, t - 30.0), t + 70.0))
            wind = [min(max(float(h["wind"]), 0.5), 17.0) for h in hours]
            result = _utci_model(tdb=tdb, tr=trs, v=wind, rh=rh, units="SI", limit_inputs=True)
            values = getattr(result, "utci", result)
            out = []
            for v, h in zip(list(values), hours):
                v = float(v)
                # Outside UTCI's valid range (very rare): use the heat index for that hour.
                out.append(round(heat_index_c(float(h["temperature"]), float(h["humidity"])), 1)
                           if math.isnan(v) else round(v, 1))
            return out, UTCI
        except Exception:
            pass
    return [round(heat_index_c(float(h["temperature"]), float(h["humidity"])), 1) for h in hours], HEAT_INDEX


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
    """
    Bands follow the UTCI categories of the same heat (score 25/50/75/95 =
    UTCI 26/32/38/46), so the label never contradicts the "feels like":
      VERY LOW  no heat stress          LOW       moderate heat stress
      MODERATE  strong heat stress      HIGH      very strong heat stress
      EXTREME   extreme heat stress, or very strong heat for most of the day
    (A typical hot afternoon in Tamil Nadu is HIGH; EXTREME is kept for the
    days that really stand out, so the label does not lose its meaning.)
    """
    if score < 25:
        return "VERY LOW"
    if score < 50:
        return "LOW"
    if score < 75:
        return "MODERATE"
    if score < 92:
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
def summarise_day(hours, lat=None, lon=None):
    """
    hours: list of hourly weather dicts (see mean_radiant_temperature).
    Returns peak stress, exposure hours and the combined score/band.
    """
    if not hours:
        return None
    stresses, model = stress_values(hours, lat, lon)
    peak = max(stresses)
    peak_i = stresses.index(peak)
    danger = SCALES[model]["danger"]
    hours_danger = sum(1 for v in stresses if v >= danger)
    score = combined_thermal_score(peak, hours_danger, model)
    temps = [h["temperature"] for h in hours]
    shade = max(stress_values(hours, lat, lon, shade=True)[0])
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
        "cloud_at_peak": hours[peak_i].get("cloud"),
        "heat_index_max": round(max(heat_index_c(h["temperature"], h["humidity"]) for h in hours), 1),
        "hourly_stress": stresses,
    }


def calculate_current(current, today_hours_danger=0, lat=None, lon=None):
    """Current conditions: instantaneous stress plus today's exposure hours."""
    value, model = stress_value(current, lat, lon)
    score = combined_thermal_score(value, today_hours_danger, model)
    return {
        "stress": value,
        "stress_shade": stress_value(current, lat, lon, shade=True)[0],
        "model": model,
        "category": stress_category(value, model),
        "heat_index": round(heat_index_c(current["temperature"], current["humidity"]), 1),
        "thermal_score": score,
        "risk": risk_band(score),
    }
