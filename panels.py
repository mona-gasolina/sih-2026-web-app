from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget
)

from config import (
    FONT_FAMILY, FS_SMALL, FS_LABEL, FS_BODY, FS_HEADING, FS_VALUE, FS_TITLE,
    set_base_style, qss_gradient, c, scaled,
    temperature_gradient, risk_gradient, risk_band_color, contrast_text,
)
from alerts import suggested_actions
from data_manager import format_population

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


class HeroCard(GradientCard):
    """Banner coloured by today's peak 'feels like'."""

    def __init__(self, name, m):
        super().__init__(temperature_gradient(m["today_peak_stress"] - 4), radius=16)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.addWidget(self.label(name, FS_TITLE + 2, 800), 1)
        top.addWidget(self.pill(f"HEAT STRESS: {m['risk']}", wrap=True), 0, Qt.AlignTop)
        layout.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(self.label(f"{m['temperature']:.1f}°C", FS_VALUE + 12, 800, wrap=False))
        details = QVBoxLayout()
        details.setSpacing(2)
        details.addWidget(self.label(
            f"Feels like {m['stress']:.0f}°C in sun, {m['stress_shade']:.0f}°C in shade", FS_BODY, 700))
        details.addWidget(self.label(
            f"Humidity {m['humidity']:.0f}%  •  Wind {m['wind'] * 3.6:.0f} km/h", FS_BODY, 500))
        row.addLayout(details, 1)
        layout.addLayout(row)
        layout.addWidget(self.label(
            f"{m['stress_category']}  •  measured with {m['stress_model']}", FS_SMALL, 600))


class MetricCard(GradientCard):
    def __init__(self, label, value, sub, gradient):
        super().__init__(gradient)
        self.setMinimumHeight(118)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        layout.addWidget(self.label(label.upper(), FS_SMALL, 800))
        layout.addWidget(self.label(value, FS_VALUE, 800, wrap=False))
        layout.addWidget(self.label(sub, FS_SMALL, 600))
        layout.addStretch()


class ForecastRow(GradientCard):
    """One compact day: day • max/min • peak feels-like • danger hours • vs normal • band."""

    def __init__(self, day):
        super().__init__(temperature_gradient(day["temp_max"]), radius=12)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(0)
        left.addWidget(self.label(day["date_text"], FS_LABEL, 800, wrap=False))
        left.addWidget(self.label(f"{day['temp_max']:.0f}° / {day['temp_min']:.0f}°", FS_HEADING + 2, 800, wrap=False))
        layout.addLayout(left)
        layout.addStretch(1)

        mid = QVBoxLayout()
        mid.setSpacing(0)
        when = f" at {day['peak_time']}" if day.get("peak_time") else ""
        mid.addWidget(self.label(f"Feels {day['stress']:.0f}°C{when}", FS_BODY, 700))
        hours = day["hours_danger"]
        mid.addWidget(self.label(
            f"{hours} h in danger range" if hours else "No hours in danger range", FS_SMALL, 600))
        if day.get("departure") is not None:
            mid.addWidget(self.label(
                f"{day['departure']:+.1f}° vs normal max {day['normal_max']:.0f}°", FS_SMALL, 600))
        layout.addLayout(mid, 3)
        right = QVBoxLayout()
        right.setSpacing(4)
        right.addWidget(self.pill(day["risk"]), 0, Qt.AlignRight)
        if day.get("heatwave", "NONE") != "NONE":
            right.addWidget(band_chip(day["heatwave"], "RED" if day["heatwave"].startswith("SEVERE") else "ORANGE"),
                            0, Qt.AlignRight)
        layout.addLayout(right)


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
            text = d["date_text"] if i < 2 else d["date_text"].split(" ")[0]
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
        for label, colour, dashed in (("Peak feels-like", feels_colour, False), ("Max air temp.", temp_colour, True)):
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
        super().__init__("HEAT-WAVE STATUS & SUGGESTED ACTIONS")
        imd, peak = m["imd"], m["peak_band"]

        status = QHBoxLayout()
        status.setSpacing(10)
        status.addWidget(band_chip(f"IMD {imd['code']}", imd["code"], FS_LABEL))
        if alert:
            status.addWidget(band_chip(alert["level"], alert["colour"], FS_LABEL))
            text = QLabel(f"{imd['label']} – {alert['confidence']}")
        else:
            text = QLabel(f"{imd['label']} – {imd['reason']}")
        text.setWordWrap(True)
        set_base_style(text, f"font-size:{FS_BODY}px;font-weight:600;")
        status.addWidget(text, 1)
        self.body.addLayout(status)

        run = imd["longest_run"]
        self.body.addLayout(kv_row("Heat-wave days in 5 days",
                                   f"{imd['hw_days']} of {len(m['forecast'])}"
                                   + (f" ({imd['severe_days']} severe)" if imd["severe_days"] else "")))
        self.body.addLayout(kv_row("Longest heat-wave spell", f"{run} day{'s' if run != 1 else ''}"))
        self.body.addLayout(kv_row("Highest heat-stress band (UTCI)", peak))
        if not m.get("has_normals"):
            self.body.addLayout(kv_row("Normals", "Not loaded – only the 45 °C rule applies"))

        divider = QFrame()
        divider.setFixedHeight(1)
        set_base_style(divider, "background:$border;")
        self.body.addWidget(divider)

        dot_colour = risk_band_color(imd["code"])
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

        foot = QLabel(f"Heat wave per IMD criteria for {m['terrain']} areas (max temperature vs the "
                      "local normal). Prototype guidance – align with the local Heat Action Plan.")
        foot.setWordWrap(True)
        set_base_style(foot, f"font-size:{FS_SMALL}px;color:$subtle;")
        self.body.addWidget(foot)


class CensusCard(SurfaceCard):
    def __init__(self, m):
        super().__init__("POPULATION EXPOSURE")
        d = m["demographic"]
        pop = d.get("population", 0)
        self.body.addLayout(kv_row("Population (Census 2011)",
                                   f"{pop:,}  ({format_population(pop)})" if pop else "Not available"))
        if d.get("male") and d.get("female"):
            share = d["female"] / (d["male"] + d["female"]) * 100
            self.body.addLayout(kv_row("Female share", f"{share:.1f}%"))
        vuln = m.get("vulnerability")
        self.body.addLayout(kv_row("Exposure score", f"{vuln:.0f} / 100" if vuln is not None else "State average used"))
        cap = m.get("capacity")
        self.body.addLayout(kv_row("Response capacity", f"{cap:.0f} / 100" if cap is not None else "Not loaded yet"))
        note = d.get("note") or ("Vulnerability uses population only for now. Elderly, outdoor-worker and "
                                 "NFHS health indicators will be added with validated data.")
        foot = QLabel(note)
        foot.setWordWrap(True)
        set_base_style(foot, f"font-size:{FS_SMALL}px;color:$subtle;")
        self.body.addWidget(foot)


# ---------------------------------------------------------------------------
# Right-hand detail panel
# ---------------------------------------------------------------------------
class DetailPanel(QFrame):
    def __init__(self, on_refresh):
        super().__init__()
        self.on_refresh = on_refresh
        self.setObjectName("detailPanel")
        set_base_style(self, f"""
            QFrame#detailPanel {{ background:$bg; border-left:1px solid $border; }}
            QWidget#detailHost {{ background:$bg; }}
            QFrame#detailFooter {{ background:$bg; border-top:1px solid $border; }}
            QScrollArea {{ background:transparent; border:none; }}
            QPushButton#refresh {{
                background:$primary;color:$onPrimary;border:none;border-radius:11px;
                padding:12px 16px;font-weight:700;font-size:{FS_BODY}px;
            }}
            QPushButton#refresh:hover {{ background:$primaryHover; }}
            QPushButton#refresh:disabled {{ background:$borderStrong; }}
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

        header = QHBoxLayout()
        title = QLabel("SELECTED AREA")
        set_base_style(title, f"font-size:{FS_LABEL}px;font-weight:800;color:$muted;")
        self.source = QLabel("LOADING")
        set_base_style(self.source, f"font-size:{FS_SMALL}px;font-weight:800;color:$text;"
                                    f"background:$chip;border-radius:7px;padding:5px 9px;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.source)
        self.content.addLayout(header)

        self.dynamic = QVBoxLayout()
        self.dynamic.setSpacing(14)
        self.content.addLayout(self.dynamic)
        self.content.addStretch(1)

        placeholder = QLabel("Click a district on the map, or pick one from the list under the map.")
        placeholder.setWordWrap(True)
        set_base_style(placeholder, f"font-size:{FS_BODY}px;color:$muted;")
        self.dynamic.addWidget(placeholder)

        footer = QFrame()
        footer.setObjectName("detailFooter")
        f_layout = QVBoxLayout(footer)
        f_layout.setContentsMargins(20, 12, 20, 14)
        self.refresh = QPushButton("Refresh live weather")
        self.refresh.setObjectName("refresh")
        self.refresh.setCursor(Qt.PointingHandCursor)
        self.refresh.clicked.connect(self.on_refresh)
        f_layout.addWidget(self.refresh)
        outer.addWidget(footer)

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
        if source:
            self.source.setText(source.upper())
        self._clear(self.dynamic)

        if not m.get("loaded"):
            waiting = QLabel(f"{item.zone_name}\n\nLoading weather…")
            set_base_style(waiting, f"font-size:{FS_HEADING}px;color:$muted;")
            self.dynamic.addWidget(waiting)
            return

        self.dynamic.addWidget(HeroCard(item.zone_name, m))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        cards = [
            ("Relative risk", f"{m['risk_score']:.0f}", "heat stress + exposure, /100",
             risk_gradient(m["risk_score"])),
            ("Thermal score", f"{m['thermal_score']:.0f}", "today's peak + duration, /100",
             risk_gradient(m["thermal_score"])),
            ("Peak feels-like", f"{m['today_peak_stress']:.0f}°C",
             f"in sun, {m['today_hours_danger']} h in danger range today",
             temperature_gradient(m["today_peak_stress"] - 4)),
            ("Heat index now", f"{m['heat_index']:.0f}°C", "temperature + humidity",
             temperature_gradient(m["heat_index"] - 4)),
        ]
        for i, (label, value, sub, gradient) in enumerate(cards):
            grid.addWidget(MetricCard(label, value, sub, gradient), i // 2, i % 2)
        self.dynamic.addLayout(grid)

        self.dynamic.addWidget(ActionsCard(m, alert))

        self.dynamic.addWidget(self._section("5-day outlook"))
        chart_card = SurfaceCard()
        chart = TrendChart()
        chart.set_forecast(m["forecast"])
        chart_card.body.addWidget(chart)
        self.dynamic.addWidget(chart_card)
        for day in m["forecast"]:
            self.dynamic.addWidget(ForecastRow(day))

        self.dynamic.addWidget(CensusCard(m))
