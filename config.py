from pathlib import Path
import colorsys
import json
import re

APP_TITLE = "HEAT INTELLIGENCE"
APP_SHORT = "Heat Intelligence"
STATE_NAME = "Tamil Nadu"
APP_VERSION = "Prototype 0.3"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MAP_FILE = DATA_DIR / "tamil_nadu.geojson"
USERS_FILE = DATA_DIR / "users.json"
UI_SETTINGS_FILE = DATA_DIR / "ui_settings.json"
WEATHER_CACHE_FILE = DATA_DIR / "weather_cache.json"
ALERT_STATE_FILE = DATA_DIR / "alert_state.json"
ALERT_LOG_FILE = DATA_DIR / "alert_log.csv"
CAPACITY_FILE = DATA_DIR / "response_capacity.csv"
NORMALS_FILE = DATA_DIR / "tmax_normals.json"

MAP_URL = (
    "https://cdn.jsdelivr.net/gh/udit-001/india-maps-data@2884453/"
    "geojson/states/tamil-nadu.geojson"
)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_TIMEOUT = 20
WEATHER_CACHE_MINUTES = 60        # PDF: cache weather, refresh every hour
FORECAST_DAYS = 5
# Daily-max normals for the IMD heat-wave departure test (archive of past forecasts).
NORMALS_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
NORMALS_YEARS = (2022, 2025)
NORMALS_SMOOTH_DAYS = 15          # ± window used to smooth the day-of-year mean

# Replay of a real past heat wave (archived Open-Meteo weather), so the warning
# flow can be shown outside the heat season. (start date, label). 30 Apr – 4 May
# 2024: IMD heat-wave warnings for interior Tamil Nadu; the IMD rules in
# heatwave.py flag 23 of 37 districts for this window.
REPLAY_EVENTS = [
    ("2024-04-30", "Heat wave, 30 Apr – 4 May 2024"),
]

# ---------------------------------------------------------------------------
# Window / layout
# ---------------------------------------------------------------------------
# Widths are in logical pixels (Windows 125 % scaling on a 1920 px screen =
# 1536 logical px). The dashboard adapts at two breakpoints; below its
# minimum size it scrolls instead of clipping.
WINDOW_WIDTH = 1700
WINDOW_HEIGHT = 980
MIN_WINDOW_WIDTH = 640
MIN_WINDOW_HEIGHT = 480
COMPACT_WIDTH = 1600              # below this: slimmer top bar and right panel
SHORT_HEIGHT = 720                # below this: map heading hidden
NARROW_WIDTH = 1400               # below this: side panel starts collapsed, no name badge
LEFT_PANEL_WIDTH = 330
LEFT_PANEL_COMPACT = 290
RIGHT_PANEL_WIDTH = 480
RIGHT_PANEL_COMPACT = 420
RIGHT_PANEL_NARROW = 380

# ---------------------------------------------------------------------------
# Typography – sized for older users (nothing below 13px at 100%)
# ---------------------------------------------------------------------------
FONT_FAMILY = "Segoe UI"
FS_SMALL = 13
FS_LABEL = 14
FS_BODY = 15
FS_HEADING = 18
FS_VALUE = 28
FS_TITLE = 24
FS_BRAND = 24

FONT_SCALE_MIN = 1.0
FONT_SCALE_MAX = 1.6
FONT_SCALE_STEP = 0.1

# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------
# Stylesheets are written with $tokens (e.g. "background:$surface") and are
# rendered with the active theme, so light/dark can be switched at runtime.
THEMES = {
    "light": {
        "bg": "#F3F5F9",
        "surface": "#FFFFFF",
        "surface2": "#EEF2F7",
        "input": "#FFFFFF",
        "border": "#D5DCE6",
        "borderStrong": "#B8C3D3",
        "text": "#0F172A",
        "muted": "#4B5A70",
        "subtle": "#56657C",
        "primary": "#1E3A8A",
        "primaryHover": "#2548B3",
        "onPrimary": "#FFFFFF",
        "accent": "#D97706",
        "focus": "#1D4ED8",
        "chip": "#E5EAF2",
        "danger": "#B91C1C",
        "dangerBg": "#FEE2E2",
        "dangerBorder": "#FCA5A5",
        "warnBg": "#FEF3C7",
        "warnText": "#92400E",
        "okBg": "#DCFCE7",
        "okText": "#166534",
        "statusBg": "#0F172A",
        "statusText": "#E2E8F0",
        "scroll": "#E5EAF2",
        "scrollHandle": "#A3AFC2",
        "mapBg": "#F3F5F9",
        "mapEdge": "#475569",
        "shadow": "rgba(15,23,42,0.10)",
    },
    "dark": {
        "bg": "#0B1220",
        "surface": "#131C2E",
        "surface2": "#1A2540",
        "input": "#0F1829",
        "border": "#27344F",
        "borderStrong": "#3A4A6B",
        "text": "#E7EDF7",
        "muted": "#A7B4CA",
        "subtle": "#94A3BD",
        "primary": "#2563EB",
        "primaryHover": "#1D4ED8",
        "onPrimary": "#FFFFFF",
        "accent": "#FBBF24",
        "focus": "#60A5FA",
        "chip": "#22304D",
        "danger": "#FCA5A5",
        "dangerBg": "#3B1219",
        "dangerBorder": "#7F1D1D",
        "warnBg": "#3A2A0B",
        "warnText": "#FCD34D",
        "okBg": "#0F2E1D",
        "okText": "#86EFAC",
        "statusBg": "#070C16",
        "statusText": "#A7B4CA",
        "scroll": "#131C2E",
        "scrollHandle": "#3A4A6B",
        "mapBg": "#0B1220",
        "mapEdge": "#0B1220",
        "shadow": "rgba(0,0,0,0.35)",
    },
}

_theme_name = "light"


def theme_name():
    return _theme_name


def c(token):
    """Current theme colour for painting code (QPainter etc.)."""
    return THEMES[_theme_name][token]


# Legacy constant names kept so older modules (s1.py/s2.py) still import.
NAVY = "#0F172A"
BLUE = "#2563EB"
AMBER = "#F59E0B"
RED = "#EF4444"
GREEN = "#10B981"

# ---------------------------------------------------------------------------
# Heat colour scales (shared by map, legend, cards)
# ---------------------------------------------------------------------------
TEMP_GRADIENT_STOPS = [
    (15.0, "#2563EB"),
    (20.0, "#06B6D4"),
    (25.0, "#10B981"),
    (30.0, "#FACC15"),
    (35.0, "#F97316"),
    (40.0, "#DC2626"),
    (45.0, "#7F1D1D"),
]

RISK_GRADIENT_STOPS = [
    (0, "#2563EB"),
    (25, "#10B981"),
    (50, "#FACC15"),
    (75, "#F97316"),
    (100, "#991B1B"),
]

RISK_ORDER = ["VERY LOW", "LOW", "MODERATE", "HIGH", "EXTREME"]


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def _mix(a, b, amount):
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    return _rgb_to_hex((
        ar + (br - ar) * amount,
        ag + (bg - ag) * amount,
        ab + (bb - ab) * amount,
    ))


def _darken(hex_color, amount):
    """Darken by lowering HSL lightness – keeps the hue, avoids muddy browns."""
    r, g, b = (v / 255.0 for v in _hex_to_rgb(hex_color))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, l - amount), min(1.0, s * 1.02))
    return _rgb_to_hex((r * 255, g * 255, b * 255))


def _interpolate(stops, value):
    if value <= stops[0][0]:
        return stops[0][1]
    if value >= stops[-1][0]:
        return stops[-1][1]
    for (v1, c1), (v2, c2) in zip(stops, stops[1:]):
        if v1 <= value <= v2:
            return _mix(c1, c2, (value - v1) / (v2 - v1))
    return stops[-1][1]


def temperature_color(temp):
    return _interpolate(TEMP_GRADIENT_STOPS, float(temp))


def risk_color(score):
    return _interpolate(RISK_GRADIENT_STOPS, max(0.0, min(100.0, float(score))))


def _relative_luminance(hex_color):
    def channel(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _hex_to_rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a, b):
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


DARK_TEXT = "#0F172A"


def contrast_text(background_hex):
    white = contrast_ratio(background_hex, "#FFFFFF")
    dark = contrast_ratio(background_hex, DARK_TEXT)
    return "#FFFFFF" if white > dark else DARK_TEXT


def readable_gradient(start, end, min_contrast=4.5):
    """
    (start, end, text) where the text colour meets WCAG AA (4.5:1) on BOTH
    ends. If neither white nor dark text passes, the colours are darkened
    (hue kept) until white text passes.
    """
    for _ in range(12):
        best_text, best = None, 0.0
        for text in ("#FFFFFF", DARK_TEXT):
            score = min(contrast_ratio(start, text), contrast_ratio(end, text))
            if score > best:
                best_text, best = text, score
        if best >= min_contrast:
            return start, end, best_text
        start, end = _darken(start, 0.035), _darken(end, 0.035)
    return start, end, "#FFFFFF"


def temperature_gradient(temp, spread=2.5):
    t = float(temp)
    return readable_gradient(temperature_color(t - spread), temperature_color(t + spread))


def risk_gradient(score, spread=7.0):
    s = float(score)
    return readable_gradient(risk_color(s - spread), risk_color(s + spread))


def humidity_gradient(humidity):
    h = max(0.0, min(100.0, float(humidity))) / 100.0
    return readable_gradient(_mix("#7DD3FC", "#1D4ED8", h * 0.8), _mix("#38BDF8", "#1E3A8A", h))


def qss_gradient(start, end):
    return (
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        f"stop:0 {start}, stop:1 {end})"
    )


def risk_band_color(band):
    """Solid colour for a risk band chip."""
    anchors = {"VERY LOW": 2, "LOW": 30, "MODERATE": 52, "HIGH": 72, "EXTREME": 92,
               # IMD heat-wave colour codes (heatwave.py)
               "GREEN": 25, "YELLOW": 50, "ORANGE": 75, "RED": 100}
    return risk_color(anchors.get(band, 50))


# ---------------------------------------------------------------------------
# Persistent UI settings (text size + theme)
# ---------------------------------------------------------------------------
_font_scale = 1.0


def _read_settings():
    try:
        return json.loads(UI_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_settings(**changes):
    try:
        data = _read_settings()
        data.update(changes)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        UI_SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_ui_settings():
    global _font_scale, _theme_name
    data = _read_settings()
    _font_scale = clamp_scale(data.get("font_scale", 1.0))
    _theme_name = data.get("theme", "light") if data.get("theme") in THEMES else "light"


# Backwards compatible name
load_font_scale = load_ui_settings


def save_font_scale(scale):
    _write_settings(font_scale=round(scale, 2))


def save_theme(name):
    _write_settings(theme=name)


def clamp_scale(scale):
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        scale = 1.0
    return round(max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, scale)), 2)


def font_scale():
    return _font_scale


def scaled(px):
    return int(round(px * _font_scale))


# ---------------------------------------------------------------------------
# Stylesheet rendering: $tokens → theme colours, font sizes → text scale
# ---------------------------------------------------------------------------
_FONT_PATTERN = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", re.IGNORECASE)
_TOKEN_PATTERN = re.compile(r"\$([A-Za-z][A-Za-z0-9]*)")
_APP_BASE_STYLE = None


def render_style(stylesheet):
    colours = THEMES[_theme_name]
    styled = _TOKEN_PATTERN.sub(lambda m: colours.get(m.group(1), m.group(0)), stylesheet)
    return _FONT_PATTERN.sub(
        lambda m: f"font-size:{max(12, round(float(m.group(1)) * _font_scale))}px",
        styled,
    )


def set_base_style(widget, stylesheet):
    """Store the raw stylesheet and apply it with the current theme + text size."""
    widget.setProperty("_base_stylesheet", stylesheet)
    widget.setStyleSheet(render_style(stylesheet))


def _apply_palette(app):
    from PyQt5.QtGui import QColor, QPalette
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(c("bg")))
    pal.setColor(QPalette.WindowText, QColor(c("text")))
    pal.setColor(QPalette.Base, QColor(c("input")))
    pal.setColor(QPalette.AlternateBase, QColor(c("surface2")))
    pal.setColor(QPalette.Text, QColor(c("text")))
    pal.setColor(QPalette.Button, QColor(c("surface")))
    pal.setColor(QPalette.ButtonText, QColor(c("text")))
    pal.setColor(QPalette.ToolTipBase, QColor(c("statusBg")))
    pal.setColor(QPalette.ToolTipText, QColor("#FFFFFF"))
    pal.setColor(QPalette.Highlight, QColor(c("primary")))
    pal.setColor(QPalette.HighlightedText, QColor(c("onPrimary")))
    pal.setColor(QPalette.PlaceholderText, QColor(c("subtle")))
    pal.setColor(QPalette.Link, QColor(c("focus")))
    app.setPalette(pal)


def set_app_style(app, stylesheet):
    global _APP_BASE_STYLE
    _APP_BASE_STYLE = stylesheet
    _apply_palette(app)
    app.setStyleSheet(render_style(stylesheet))


def restyle(root=None):
    """Re-render every stored stylesheet (after a theme or text-size change)."""
    from PyQt5.QtWidgets import QApplication, QWidget
    app = QApplication.instance()
    if app is not None:
        _apply_palette(app)
        if _APP_BASE_STYLE:
            app.setStyleSheet(render_style(_APP_BASE_STYLE))
        roots = [root] if root is not None else app.topLevelWidgets()
    else:
        roots = [root] if root is not None else []
    for top in roots:
        for widget in [top] + top.findChildren(QWidget):
            base = widget.property("_base_stylesheet")
            if base:
                widget.setStyleSheet(render_style(base))
            if hasattr(widget, "on_theme_changed"):
                widget.on_theme_changed()
        top.update()


def apply_font_scale(root, scale):
    global _font_scale
    _font_scale = clamp_scale(scale)
    restyle(root)


def set_theme(name, root=None):
    global _theme_name
    if name in THEMES:
        _theme_name = name
        restyle(root)
