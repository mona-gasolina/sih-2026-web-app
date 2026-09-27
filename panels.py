from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget
)

from config import (
    FONT_FAMILY, FS_SMALL, FS_LABEL, FS_BODY, FS_HEADING, FS_VALUE, FS_TITLE,
    set_base_style, qss_gradient, c, scaled,
    temperature_gradient, risk_band_color, contrast_text,
)
from alerts import suggested_actions

def _pill_bg(text_color):
    return "rgba(255,255,255,0.22)" if text_color.upper() == "#FFFFFF" else "rgba(15,23,42,0.10)"


def band_chip(text, band, size=FS_SMALL):
    colour = risk_band_color(band)
    chip = QLabel(text)
    set_base_style(chip, f"font-size:{size}px;font-weight:800;color:{contrast_text(colour)};"
                         f"background:{colour};border-radius:7px;padding:4px 9px;")
    return chip


class SurfaceCard(QFrame):
    """Plain themed card with an optional small-caps title."""

    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("surfaceCard")
        set_base_style(self, """
            QFrame#surfaceCard { background:$surface; border:1px solid $border; border-radius:14px; }
            QLabel { background:transparent; border:none; color:$text; }
        """)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(10)
        if title:
            head = QLabel(title)
            head.setWordWrap(True)
            set_base_style(head, f"font-size:{FS_LABEL}px;font-weight:800;color:$muted;")
            self.body.addWidget(head)


def kv_row(label, value, value_style=""):
    row = QHBoxLayout()
    row.setSpacing(12)
    k = QLabel(label)
    k.setWordWrap(True)
    set_base_style(k, f"font-size:{FS_BODY}px;color:$muted;")
    v = QLabel(value)
    v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    v.setWordWrap(True)
    set_base_style(v, f"font-size:{FS_BODY}px;font-weight:700;color:$text;{value_style}")
    row.addWidget(k, 1)
    row.addWidget(v)
    return row


# ---------------------------------------------------------------------------
# Gradient cards
# ---------------------------------------------------------------------------
class GradientCard(QFrame):
    def __init__(self, gradient, radius=14, parent=None):
        super().__init__(parent)
        start, end, text = gradient
        self.text_color = text
        self.setObjectName("gcard")
        set_base_style(self, f"""
            QFrame#gcard {{ background:{qss_gradient(start, end)}; border:none; border-radius:{radius}px; }}
            QLabel {{ color:{text}; background:transparent; border:none; }}
        """)

    def label(self, text, size, weight=400, wrap=True):
        lbl = QLabel(text)
        set_base_style(lbl, f"font-size:{size}px;font-weight:{weight};")
        lbl.setWordWrap(wrap)
        return lbl

    def pill(self, text, size=FS_LABEL, wrap=False):
        pill = QLabel(text)
        pill.setWordWrap(wrap)
        set_base_style(pill, f"font-size:{size}px;font-weight:800;color:{self.text_color};"
                             f"background:{_pill_bg(self.text_color)};border-radius:8px;padding:6px 10px;")
        return pill


CODE_NAMES = {"GREEN": "No heat wave", "YELLOW": "Yellow alert", "ORANGE": "Orange alert", "RED": "Red alert"}
MODEL_NAMES = {"ecmwf_ifs025": "ECMWF", "gfs_seamless": "GFS", "icon_seamless": "ICON"}


def friendly_reason(imd):
    """IMD summary in everyday words."""
    if imd["code"] != "GREEN":
        run = imd["longest_run"]
        return (f"{imd['hw_days']} heat-wave day{'s' if imd['hw_days'] != 1 else ''} in the next "
                f"5 days, {run} in a row.")
    if imd["hw_days"]:
        return "One unusually hot day is coming. IMD only calls it a heat wave after two in a row."
    return "Temperatures are within the usual range for this time of year."


class HeroCard(GradientCard):
    """The selected district: now, and how hot it will feel today."""

    def __init__(self, name, m):
        super().__init__(temperature_gradient(m["today_peak_stress"] - 4), radius=16)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.addWidget(self.label(name, FS_TITLE + 2, 800), 1)
        top.addWidget(self.pill(f"Today: {m['risk'].lower()} heat stress", wrap=True), 0, Qt.AlignTop)
        layout.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(self.label(f"{m['temperature']:.0f}°C", FS_VALUE + 12, 800, wrap=False))
        details = QVBoxLayout()
        details.setSpacing(2)
        details.addWidget(self.label(
            f"Feels like {m['stress']:.0f}° in the sun, {m['stress_shade']:.0f}° in the shade", FS_BODY, 700))
        cloud = f"  ·  Cloud {m['cloud']:.0f}%" if m.get("cloud") is not None else ""
        details.addWidget(self.label(
            f"Humidity {m['humidity']:.0f}%  ·  Wind {m['wind'] * 3.6:.0f} km/h{cloud}", FS_BODY, 500))
        row.addLayout(details, 1)
        layout.addLayout(row)
        category = self.label(f"Right now: {m['stress_category'].lower()}", FS_SMALL, 600)
        category.setToolTip(f"{m['stress_model']} – how hot it feels to the body, counting sun, "
                            "humidity, wind and heat from the ground.")
        layout.addWidget(category)


class StatTile(QFrame):
    """Small number tile: label, value (with a coloured bar) and one line of context."""

    def __init__(self, label, value, sub, colour, tooltip=""):
        super().__init__()
        self.setObjectName("statTile")
        set_base_style(self, f"""
            QFrame#statTile {{ background:$surface; border:1px solid $border; border-radius:12px;
                               border-left:5px solid {colour}; }}
            QLabel {{ background:transparent; border:none; }}
        """)
        self.setToolTip(tooltip)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(2)
        for text, style, wrap in ((label, f"font-size:{FS_SMALL}px;font-weight:700;color:$muted;", True),
                                  (value, f"font-size:{FS_VALUE - 2}px;font-weight:800;color:$text;", False),
                                  (sub, f"font-size:{FS_SMALL}px;color:$subtle;", True)):
            lbl = QLabel(text)
            lbl.setWordWrap(wrap)
            set_base_style(lbl, style)
            layout.addWidget(lbl)
        layout.addStretch()


class ForecastList(SurfaceCard):
    """The next 5 days as one tidy list instead of five big coloured boxes."""

    def __init__(self, forecast):
        super().__init__()
        self.body.setSpacing(0)
        self.body.setContentsMargins(16, 6, 16, 6)
        for i, day in enumerate(forecast):
            if i:
                line = QFrame()
                line.setFixedHeight(1)
                set_base_style(line, "background:$border;")
                self.body.addWidget(line)
            self.body.addWidget(self._row(day))

    def _row(self, day):
        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 10, 0, 10)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)

        name = QLabel(day["date_text"])
        set_base_style(name, f"font-size:{FS_BODY}px;font-weight:800;color:$text;")
        temps = QLabel(f"{day['temp_max']:.0f}°  <span style='color:{c('subtle')}'>/ {day['temp_min']:.0f}°</span>")
        set_base_style(temps, f"font-size:{FS_BODY}px;font-weight:800;color:$text;")
        feels = QLabel(f"Feels {day['stress']:.0f}°" + (f" at {day['peak_time']}" if day.get("peak_time") else ""))
        set_base_style(feels, f"font-size:{FS_SMALL}px;color:$muted;")
        extra = []
        if day["hours_danger"]:
            extra.append(f"{day['hours_danger']} h of very strong heat")
        if day.get("departure") is not None:
            extra.append(f"{day['departure']:+.1f}° vs usual")
        detail = QLabel("  ·  ".join(extra) or "No hours of very strong heat")
        detail.setWordWrap(True)
        set_base_style(detail, f"font-size:{FS_SMALL}px;color:$subtle;")

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addStretch()
        if day.get("heatwave", "NONE") != "NONE":
            severe = day["heatwave"].startswith("SEVERE")
            chips.addWidget(band_chip("Severe heat wave" if severe else "Heat wave", "RED" if severe else "ORANGE"))
        chips.addWidget(band_chip(day["risk"].title(), day["risk"]))

        grid.addWidget(name, 0, 0)
        grid.addWidget(temps, 0, 1, Qt.AlignRight)
        grid.addWidget(feels, 1, 0)
        grid.addLayout(chips, 1, 1)
        grid.addWidget(detail, 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        return row



# ---------------------------------------------------------------------------
# 5-day trend chart
# ---------------------------------------------------------------------------
class TrendChart(QWidget):
    """Max air temperature vs. peak 'feels like'; dots coloured by the day's risk band."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.forecast = []
        self.setMinimumHeight(scaled(190))

    def set_forecast(self, forecast):
        self.forecast = forecast
        self.setMinimumHeight(scaled(190))
        self.update()

    def on_theme_changed(self):
        self.setMinimumHeight(scaled(190))
        self.update()

    def paintEvent(self, event):
        if not self.forecast:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        small = QFont(FONT_FAMILY)
        small.setPixelSize(scaled(FS_SMALL))
        fm = QFontMetrics(small)
        p.setFont(small)

        legend_h = fm.height() + 8
        left, right = fm.horizontalAdvance("50°") + 10, 14
        top, bottom = legend_h + 10, fm.height() + 10
        plot = QRectF(left, top, max(40, self.width() - left - right), max(40, self.height() - top - bottom))

        temps = [d["temp_max"] for d in self.forecast]
        feels = [d["stress"] for d in self.forecast]
        lo = 5 * int((min(temps + feels) - 2) // 5)
        hi = 5 * int((max(temps + feels) + 2) // 5 + 1)
        n = len(self.forecast)

        def pt(i, v):
            x = plot.left() + (plot.width() * (i / (n - 1) if n > 1 else 0.5))
            y = plot.bottom() - (v - lo) / (hi - lo) * plot.height()
            return QPointF(x, y)

        for v in range(lo, hi + 1, 5):
            y = pt(0, v).y()
            p.setPen(QPen(QColor(c("border")), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(c("muted")))
            p.drawText(QRectF(0, y - fm.height() / 2, left - 6, fm.height()), Qt.AlignRight | Qt.AlignVCenter, f"{v}°")

        p.setPen(QColor(c("muted")))
        for i, d in enumerate(self.forecast):
            text = d["date_text"] if d["date_text"] in ("Today", "Tomorrow") else d["date_text"].split(" ")[0]
            w = fm.horizontalAdvance(text)
            x = max(0.0, min(pt(i, lo).x() - w / 2, self.width() - w - 2))
            p.drawText(QRectF(x, plot.bottom() + 6, w + 4, fm.height()), Qt.AlignLeft, text)

        def line(values, colour, dashed=False):
            path = QPainterPath(pt(0, values[0]))
            for i, v in enumerate(values[1:], 1):
                path.lineTo(pt(i, v))
            pen = QPen(QColor(colour), 3)
            if dashed:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

        temp_colour, feels_colour = c("subtle"), c("text")
        line(temps, temp_colour, dashed=True)
        line(feels, feels_colour)
        for i, d in enumerate(self.forecast):
            p.setPen(QPen(QColor(c("surface")), 2))
            p.setBrush(QColor(risk_band_color(d["risk"])))
            p.drawEllipse(pt(i, feels[i]), 7, 7)

        x = plot.left()
        for label, colour, dashed in (("Feels like (max)", feels_colour, False), ("Air temperature (max)", temp_colour, True)):
            pen = QPen(QColor(colour), 3)
            if dashed:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(x, legend_h / 2), QPointF(x + 22, legend_h / 2))
            p.setPen(QColor(c("text")))
            w = fm.horizontalAdvance(label)
            p.drawText(QRectF(x + 28, 0, w + 4, legend_h), Qt.AlignVCenter, label)
            x += 28 + w + 20
        p.end()


# ---------------------------------------------------------------------------
# Alert status + actions, population
# ---------------------------------------------------------------------------
class ActionsCard(SurfaceCard):
    def __init__(self, m, alert=None):
        super().__init__("HEAT-WAVE STATUS")
        imd, peak = m["imd"], m["peak_band"]
        self.setToolTip(f"Uses IMD's heat-wave rules for {m['terrain']} districts: how far the day's "
                        "maximum is above the usual maximum for that date.")

        status = QHBoxLayout()
        status.setSpacing(10)
        status.addWidget(band_chip(CODE_NAMES.get(imd["code"], imd["code"]), imd["code"], FS_LABEL), 0, Qt.AlignTop)
        if alert:
            status.addWidget(band_chip(alert["level"].title(), alert["colour"], FS_LABEL), 0, Qt.AlignTop)
        status.addStretch()
        self.body.addLayout(status)
        text = QLabel(alert["confidence"] + "." if alert else friendly_reason(imd))
        text.setWordWrap(True)
        set_base_style(text, f"font-size:{FS_BODY}px;")
        self.body.addWidget(text)

        run = imd["longest_run"]
        self.body.addLayout(kv_row("Heat-wave days (next 5)",
                                   f"{imd['hw_days']}" + (f", {imd['severe_days']} severe" if imd["severe_days"] else "")))
        if imd["hw_days"]:
            self.body.addLayout(kv_row("Longest run", f"{run} day{'s' if run != 1 else ''}"))
        ens = m.get("ensemble") or {}
        if ens.get("total") and (imd["code"] != "GREEN" or ens.get("agree")):
            row = kv_row("Other forecasts that agree", f"{ens['agree']} of {ens['total']}")
            self.body.addLayout(row)
            detail = QLabel("  ·  ".join(f"{MODEL_NAMES.get(k, k)}: {CODE_NAMES.get(v, v).lower()}"
                                         for k, v in ens["codes"].items()))
            detail.setWordWrap(True)
            detail.setToolTip("The same test run on three independent weather forecasts, each corrected "
                              "for running warm or cool. A warning needs at least one to agree.")
            set_base_style(detail, f"font-size:{FS_SMALL}px;color:$subtle;")
            self.body.addWidget(detail)
        self.body.addLayout(kv_row("Worst heat stress this week", peak.title()))
        if not m.get("has_normals"):
            self.body.addLayout(kv_row("Usual temperatures", "Not loaded – 45 °C rule only"))

        divider = QFrame()
        divider.setFixedHeight(1)
        set_base_style(divider, "background:$border;")
        self.body.addWidget(divider)
        what = QLabel("What to do")
        set_base_style(what, f"font-size:{FS_BODY}px;font-weight:800;")
        self.body.addWidget(what)

        dot_colour = risk_band_color(imd["code"] if imd["code"] != "GREEN" else peak)
        for action in suggested_actions(m):
            row = QHBoxLayout()
            row.setSpacing(10)
            dot = QLabel("●")
            set_base_style(dot, f"font-size:{FS_SMALL}px;color:{dot_colour};")
            row.addWidget(dot, 0, Qt.AlignTop)
            label = QLabel(action)
            label.setWordWrap(True)
            set_base_style(label, f"font-size:{FS_BODY}px;")
            row.addWidget(label, 1)
            self.body.addLayout(row)


class CensusCard(SurfaceCard):
    def __init__(self, m):
        super().__init__("PEOPLE")
        d = m["demographic"]
        pop = d.get("population", 0)
        self.body.addLayout(kv_row("Population (2011 census)",
                                   f"{pop:,}" if pop else "Not available"))
        if d.get("male") and d.get("female"):
            share = d["female"] / (d["male"] + d["female"]) * 100
            self.body.addLayout(kv_row("Women", f"{share:.1f}%"))
        vuln = m.get("vulnerability")
        exposure = kv_row("Exposure score", f"{vuln:.0f} / 100" if vuln is not None else "State average")
        self.body.addLayout(exposure)
        cap = m.get("capacity")
        if cap is not None:
            self.body.addLayout(kv_row("Response capacity", f"{cap:.0f} / 100"))
        note = d.get("note") or ("Census 2011 is still India's latest official count – Census 2027 "
                                 "figures will replace it. Age and outdoor-work data come next.")
        foot = QLabel(note)
        foot.setWordWrap(True)
        set_base_style(foot, f"font-size:{FS_SMALL}px;color:$subtle;")
        self.body.addWidget(foot)


# ---------------------------------------------------------------------------
# Right-hand detail panel
# ---------------------------------------------------------------------------
class DetailPanel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("detailPanel")
        set_base_style(self, """
            QFrame#detailPanel { background:$bg; border-left:1px solid $border; }
            QWidget#detailHost { background:$bg; }
            QScrollArea { background:transparent; border:none; }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("detailHost")
        self.content = QVBoxLayout(host)
        self.content.setContentsMargins(20, 18, 20, 18)
        self.content.setSpacing(14)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        self.dynamic = QVBoxLayout()
        self.dynamic.setSpacing(14)
        self.content.addLayout(self.dynamic)
        self.content.addStretch(1)

        placeholder = QLabel("Pick a district on the map to see its details.")
        placeholder.setWordWrap(True)
        set_base_style(placeholder, f"font-size:{FS_BODY}px;color:$muted;")
        self.dynamic.addWidget(placeholder)

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def update(self, item=None):
        # update() without an item is Qt's normal repaint.
        if item is None:
            return super().update()
        return self.show_item(item)

    def _section(self, text):
        label = QLabel(text)
        set_base_style(label, f"font-size:{FS_HEADING}px;font-weight:800;color:$text;")
        return label

    def show_item(self, item, source="", alert=None):
        m = item.metrics
        self._clear(self.dynamic)

        if not m.get("loaded"):
            waiting = QLabel(f"{item.zone_name}\n\nGetting the forecast…")
            set_base_style(waiting, f"font-size:{FS_HEADING}px;color:$muted;")
            self.dynamic.addWidget(waiting)
            return

        self.dynamic.addWidget(HeroCard(item.zone_name, m))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        hours = m["today_hours_danger"]
        tiles = [
            ("Risk score", f"{m['risk_score']:.0f}", "heat, plus how many people live here",
             risk_band_color(m["risk"]),
             "0–100. 70% how hot it feels today, 30% how many people are exposed."),
            ("Heat score", f"{m['thermal_score']:.0f}", "today's peak and how long it lasts",
             risk_band_color(m["risk"]),
             "0–100. 75% the hottest it will feel, 25% the hours of very strong heat."),
            ("Hottest it'll feel", f"{m['today_peak_stress']:.0f}°",
             f"in the sun · {hours} h of very strong heat" if hours else "in the sun",
             temperature_gradient(m["today_peak_stress"] - 4)[0],
             "UTCI 'feels like' temperature for someone standing in the sun."),
            ("Heat index now", f"{m['heat_index']:.0f}°", "temperature with humidity",
             temperature_gradient(m["heat_index"] - 4)[0],
             "The heat index most weather services use (in the shade)."),
        ]
        for i, (label, value, sub, colour, tip) in enumerate(tiles):
            grid.addWidget(StatTile(label, value, sub, colour, tip), i // 2, i % 2)
        self.dynamic.addLayout(grid)

        self.dynamic.addWidget(ActionsCard(m, alert))

        self.dynamic.addWidget(self._section("Next 5 days"))
        chart_card = SurfaceCard()
        chart = TrendChart()
        chart.set_forecast(m["forecast"])
        chart_card.body.addWidget(chart)
        self.dynamic.addWidget(chart_card)
        self.dynamic.addWidget(ForecastList(m["forecast"]))

        self.dynamic.addWidget(CensusCard(m))
