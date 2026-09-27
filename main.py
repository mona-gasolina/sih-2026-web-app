import sys
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, QRectF
from PyQt5.QtGui import QColor, QPainter, QBrush, QLinearGradient, QFont, QFontMetrics, QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QPushButton, QScrollArea, QShortcut, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget
)

import alerts as alert_engine
from auth import AuthManager
from config import (
    APP_TITLE, APP_SHORT, APP_VERSION, STATE_NAME, WINDOW_HEIGHT, WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, COMPACT_WIDTH, NARROW_WIDTH,
    LEFT_PANEL_WIDTH, RIGHT_PANEL_WIDTH, RIGHT_PANEL_COMPACT, RIGHT_PANEL_NARROW,
    REPLAY_EVENTS, WEATHER_CACHE_MINUTES, FONT_FAMILY,
    FS_SMALL, FS_LABEL, FS_BODY, FS_HEADING, FS_TITLE, FS_BRAND, FS_VALUE,
    FONT_SCALE_STEP, TEMP_GRADIENT_STOPS, RISK_GRADIENT_STOPS,
    set_base_style, set_app_style, load_ui_settings, font_scale, scaled, c,
    risk_band_color, contrast_text,
)
from data_manager import (
    load_census_profiles, get_property, geometry_centroid, load_geojson, load_response_capacity,
    format_population,
)
from login import LoginDialog, AccessManagerDialog, FORM_STYLE
from map_view import TamilNaduMap
from panels import DetailPanel, band_chip
from heatwave import code_index
from pipeline import placeholder_metrics
from thermal import engine_name
from ui_controls import TextSizeControl, ThemeToggle, fit_to_screen
from service import compute_all


APP_STYLE = f"""
    QWidget {{ font-family: "{FONT_FAMILY}"; font-size:{FS_BODY}px; color:$text; }}
    QMainWindow, QDialog {{ background:$bg; }}
    QToolTip {{
        background:$statusBg; color:#FFFFFF; border:1px solid $border; padding:8px 10px;
        font-size:{FS_BODY}px;
    }}
    QComboBox QAbstractItemView {{
        background:$surface; color:$text; border:1px solid $border;
        selection-background-color:$primary; selection-color:$onPrimary;
        font-size:{FS_BODY}px; padding:4px; outline:none;
    }}
    QMessageBox {{ background:$surface; }}
    QMessageBox QLabel {{ color:$text; font-size:{FS_BODY}px; }}
    QMessageBox QPushButton {{
        background:$surface2; color:$text; border:1px solid $border; border-radius:8px;
        padding:8px 18px; min-width:80px;
    }}
    QScrollBar:vertical {{ background:$scroll; width:14px; margin:0; }}
    QScrollBar:horizontal {{ background:$scroll; height:14px; margin:0; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background:$scrollHandle; border-radius:6px; margin:2px;
    }}
    QScrollBar::handle:vertical {{ min-height:40px; }}
    QScrollBar::handle:horizontal {{ min-width:40px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background:none; }}
"""

COMBO_STYLE = (
    f"QComboBox {{ background:$input;border:1.5px solid $border;border-radius:10px;"
    f"padding:10px 12px;color:$text;font-size:{FS_BODY}px; }}"
    f"QComboBox:hover {{ border-color:$borderStrong; }}"
    f"QComboBox:focus {{ border:2px solid $focus; }}"
)


# ---------------------------------------------------------------------------
# Background weather + thermal computation
# ---------------------------------------------------------------------------
class WeatherWorker(QThread):
    finished_data = pyqtSignal(object, object)

    def __init__(self, locations, demographics, capacities, force=False, replay=None):
        super().__init__()
        self.locations = locations
        self.demographics = demographics
        self.capacities = capacities
        self.force = force
        self.replay = replay

    def run(self):
        results, info = compute_all(self.locations, self.demographics, self.capacities,
                                    force=self.force, replay=self.replay)
        self.finished_data.emit(results, info)


# ---------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------
class GradientLegend(QWidget):
    """Continuous legend using exactly the map colours."""

    def __init__(self, mode="Temperature", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.on_theme_changed()

    def on_theme_changed(self):
        s = font_scale()
        self.setFixedHeight(int(FS_LABEL * s + 10 + 20 + 8 + FS_SMALL * s + 8))
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        width = self.width()
        title_font = QFont(FONT_FAMILY)
        title_font.setPixelSize(scaled(FS_LABEL))
        title_font.setBold(True)
        label_font = QFont(FONT_FAMILY)
        label_font.setPixelSize(scaled(FS_SMALL))
        label_font.setWeight(QFont.DemiBold)

        p.setFont(title_font)
        p.setPen(QColor(c("text")))
        title_h = QFontMetrics(title_font).height()
        title = ("AIR TEMPERATURE NOW (°C)" if self.mode == "Temperature"
                 else "TODAY'S RELATIVE RISK  (0 = low, 100 = extreme)")
        p.drawText(QRectF(0, 0, width, title_h), Qt.AlignLeft | Qt.AlignVCenter, title)

        bar = QRectF(2, title_h + 8, max(80, width - 4), 20)
        gradient = QLinearGradient(bar.left(), 0, bar.right(), 0)
        if self.mode == "Temperature":
            lo, hi = TEMP_GRADIENT_STOPS[0][0], TEMP_GRADIENT_STOPS[-1][0]
            for t, colour in TEMP_GRADIENT_STOPS:
                gradient.setColorAt((t - lo) / (hi - lo), QColor(colour))
            labels = [((t - lo) / (hi - lo), f"{t:.0f}°") for t, _ in TEMP_GRADIENT_STOPS]
            labels[0], labels[-1] = (0.0, f"≤{lo:.0f}°"), (1.0, f"{hi:.0f}°+")
        else:
            for s, colour in RISK_GRADIENT_STOPS:
                gradient.setColorAt(s / 100.0, QColor(colour))
            labels = [(s / 100.0, str(s)) for s, _ in RISK_GRADIENT_STOPS]
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gradient))
        p.drawRoundedRect(bar, 8, 8)

        p.setFont(label_font)
        p.setPen(QColor(c("muted")))
        fm = QFontMetrics(label_font)
        for pos, text in labels:
            w = fm.horizontalAdvance(text)
            x = max(0.0, min(bar.left() + pos * bar.width() - w / 2, width - w))
            p.drawText(QRectF(x, bar.bottom() + 5, w + 2, fm.height()), Qt.AlignLeft, text)
        p.end()


class ClickableRow(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("clickRow")
        self.setCursor(Qt.PointingHandCursor)
        set_base_style(self, """
            QFrame#clickRow { background:$surface; border:1px solid $border; border-radius:10px; }
            QFrame#clickRow:hover { background:$surface2; border-color:$borderStrong; }
            QLabel { background:transparent; border:none; color:$text; }
        """)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(12, 9, 12, 9)
        self.row.setSpacing(10)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class KpiTile(QFrame):
    def __init__(self, caption, parent=None):
        super().__init__(parent)
        self.setObjectName("kpi")
        self._accent = "#94A3B8"
        self.caption = QLabel(caption.upper())
        self.value = QLabel("—")
        self.sub = QLabel("Loading…")
        self.caption.setWordWrap(True)
        self.sub.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        layout.addWidget(self.caption)
        layout.addWidget(self.value)
        layout.addWidget(self.sub)
        set_base_style(self.caption, f"font-size:{FS_SMALL}px;font-weight:800;color:$muted;")
        set_base_style(self.value, f"font-size:{FS_VALUE - 2}px;font-weight:800;color:$text;")
        set_base_style(self.sub, f"font-size:{FS_SMALL}px;color:$muted;")
        self._style()

    def _style(self):
        set_base_style(self, f"""
            QFrame#kpi {{ background:$surface; border:1px solid $border;
                          border-left:6px solid {self._accent}; border-radius:12px; }}
            QLabel {{ background:transparent; border:none; }}
        """)

    def set(self, value, sub, accent=None):
        self.value.setText(value)
        self.sub.setText(sub)
        if accent and accent != self._accent:
            self._accent = accent
            self._style()


class CollapsiblePanel(QFrame):
    COLLAPSED_WIDTH = 60

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.expanded = True
        self.setObjectName("leftPanel")
        set_base_style(self, "QFrame#leftPanel { background:$surface; border-right:1px solid $border; }"
                             "QWidget#leftBody { background:$surface; }"
                             "QScrollArea { background:transparent; border:none; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 10, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.toggle = QToolButton(text="☰")
        self.toggle.setAutoRaise(True)
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setToolTip("Show / hide the side panel")
        set_base_style(self.toggle, "QToolButton { font-size:24px;color:$text;border:none;padding:2px 8px; }"
                                    "QToolButton:hover { background:$chip;border-radius:8px; }")
        self.toggle.clicked.connect(self.toggle_panel)
        self.title = QLabel(title)
        set_base_style(self.title, f"font-size:{FS_HEADING}px;font-weight:800;color:$text;")
        header.addWidget(self.toggle)
        header.addWidget(self.title)
        header.addStretch()
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("leftBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 8, 6, 0)
        self.body_layout.setSpacing(12)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)
        self.apply_width()

    def expanded_width(self):
        return int(LEFT_PANEL_WIDTH * (1 + (font_scale() - 1) * 0.7))

    def apply_width(self):
        self.setFixedWidth(self.expanded_width() if self.expanded else self.COLLAPSED_WIDTH)

    def toggle_panel(self):
        self.set_expanded(not self.expanded)

    def set_expanded(self, expanded):
        self.expanded = expanded
        self.title.setVisible(self.expanded)
        self.scroll.setVisible(self.expanded)
        self.apply_width()


def section_label(text):
    label = QLabel(text)
    set_base_style(label, f"font-size:{FS_LABEL}px;font-weight:800;color:$muted;")
    return label


def muted_label(text):
    label = QLabel(text)
    label.setWordWrap(True)
    set_base_style(label, f"font-size:{FS_SMALL}px;color:$subtle;")
    return label


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def _log_time(stamp):
    try:
        return datetime.fromisoformat(stamp).strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return stamp or ""


class AlertLogDialog(QDialog):
    COLUMNS = [("timestamp", "When"), ("district", "District"), ("level", "Level"),
               ("risk", "Heat-wave code"), ("recipient", "Sent to"), ("channel", "Channel"),
               ("status", "Status")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Alert log")
        self.setMinimumSize(560, 380)
        fit_to_screen(self, 1180, 660)
        set_base_style(self, FORM_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)
        title = QLabel("Alert log")
        title.setObjectName("heading")
        layout.addWidget(title)
        channels = alert_engine.gateway_status()
        sub = QLabel(
            f"Gateway: {', '.join(channels)} via Twilio" if channels else
            "SMS/WhatsApp gateway not configured – alerts are recorded here only. "
            "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM to send real messages."
        )
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        self.rows = alert_engine.read_log()
        table = QTableWidget(len(self.rows), len(self.COLUMNS))
        table.setHorizontalHeaderLabels([title for _, title in self.COLUMNS])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().setDefaultSectionSize(44)
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)      # "Sent to" takes the spare width
        for r, row in enumerate(self.rows):
            for col, (key, _) in enumerate(self.COLUMNS):
                value = _log_time(row.get(key)) if key == "timestamp" else row.get(key, "")
                cell = QTableWidgetItem(value)
                cell.setToolTip(row.get("message", ""))
                table.setItem(r, col, cell)
        table.itemSelectionChanged.connect(
            lambda: self._show_message(table.currentRow()))
        layout.addWidget(table, 1)

        self.message = QLabel("No alerts have been logged yet." if not self.rows else
                              "Select a row to read the full message.")
        self.message.setObjectName("info")
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.message)
        close = QPushButton("Close")
        close.setObjectName("secondary")
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignRight)

    def _show_message(self, row):
        if 0 <= row < len(self.rows):
            self.message.setText(self.rows[row].get("message", "") or "No message text was logged.")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, user, auth_manager):
        super().__init__()
        self.user = user
        self.auth = auth_manager
        self.worker = None
        self.selected_item = None
        self.weather_info = {}
        self.alerts = []
        self.census = load_census_profiles()
        self.capacities = load_response_capacity()
        self.zone_centroids = {}
        self.replay = None                  # start date while replaying a past heat wave
        self._compact = self._narrow = None

        self.setWindowTitle(f"{APP_SHORT} • {STATE_NAME}")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.build_ui()
        self.install_shortcuts()
        self.after_scale_change()
        self.prepare_locations()
        self.load_weather(force=False)

        # PDF: re-compute every hour (APScheduler in production).
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(lambda: self.replay or self.load_weather(force=False))
        self.refresh_timer.start(WEATHER_CACHE_MINUTES * 60 * 1000)

    # ------------------------------------------------------------------ layout
    def build_ui(self):
        self.page = QWidget()
        self.page.setObjectName("page")
        set_base_style(self.page, "QWidget#page { background:$bg; }")
        root = QVBoxLayout(self.page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_top_bar())

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_left_panel())
        row.addWidget(self._build_centre(), 1)
        self.detail = DetailPanel(lambda: self.load_weather(force=True))
        row.addWidget(self.detail)
        root.addLayout(row, 1)

        self.status = QLabel()
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        set_base_style(self.status, f"background:$statusBg;color:$statusText;font-size:{FS_SMALL}px;padding:9px 16px;")
        root.addWidget(self.status)
        self._update_status()

        # Below the layout's minimum size the page scrolls instead of clipping.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.page)
        self.setCentralWidget(self.scroll)

    def _build_top_bar(self):
        top = QFrame()
        top.setObjectName("topBar")
        set_base_style(top, "QFrame#topBar { background:$surface; border-bottom:1px solid $border; }"
                            "QLabel { background:transparent; }")
        layout = QHBoxLayout(top)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(14)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel(APP_TITLE)
        set_base_style(brand, f"font-size:{FS_BRAND}px;font-weight:800;color:$text;")
        self.subtitle = QLabel("Extreme Heatwave Early Warning  •  Human Thermal Stress Index")
        self.subtitle.setWordWrap(True)
        set_base_style(self.subtitle, f"font-size:{FS_BODY}px;color:$muted;")
        brand_box.addWidget(brand)
        brand_box.addWidget(self.subtitle)
        layout.addLayout(brand_box, 1)

        self.updated_label = QLabel("Loading weather…")
        self.updated_label.setWordWrap(True)
        set_base_style(self.updated_label, f"font-size:{FS_SMALL}px;color:$muted;")
        self.updated_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.updated_label)

        self.theme_toggle = ThemeToggle()
        layout.addWidget(self.theme_toggle, 0, Qt.AlignVCenter)
        self.size_control = TextSizeControl()
        self.size_control.changed.connect(lambda _: self.after_scale_change())
        layout.addWidget(self.size_control, 0, Qt.AlignVCenter)

        who = self.user.get("full_name") or self.user["username"]
        role = "System Admin" if self.user["role"] == "admin" else "City Administrator"
        where = self.user.get("district") or self.user.get("city") or STATE_NAME
        self.badge_full, self.badge_short = f"{who}\n{role} • {where}", who
        self.badge = badge = QLabel(self.badge_full)
        badge.setToolTip(f"{who} – {role}, {where}")
        set_base_style(badge, f"font-size:{FS_SMALL}px;font-weight:700;color:$text;"
                              f"background:$chip;border-radius:10px;padding:7px 12px;")
        layout.addWidget(badge, 0, Qt.AlignVCenter)

        if self.user["role"] == "admin":
            manage = QPushButton("Manage Access")
            manage.setCursor(Qt.PointingHandCursor)
            set_base_style(manage, f"QPushButton {{ background:$primary;color:$onPrimary;border:none;"
                                   f"border-radius:11px;padding:11px 16px;font-weight:700;font-size:{FS_BODY}px; }}"
                                   f"QPushButton:hover {{ background:$primaryHover; }}")
            manage.clicked.connect(self.open_access_manager)
            layout.addWidget(manage, 0, Qt.AlignVCenter)

        sign_out = QPushButton("Sign out")
        sign_out.setCursor(Qt.PointingHandCursor)
        set_base_style(sign_out, f"QPushButton {{ background:transparent;color:$text;border:1.5px solid $border;"
                                 f"border-radius:11px;padding:10px 14px;font-weight:700;font-size:{FS_BODY}px; }}"
                                 f"QPushButton:hover {{ background:$chip; }}")
        sign_out.clicked.connect(self.sign_out)
        layout.addWidget(sign_out, 0, Qt.AlignVCenter)
        return top

    def _build_left_panel(self):
        self.left = CollapsiblePanel("OVERVIEW")
        body = self.left.body_layout

        body.addWidget(section_label("MAP LAYER"))
        self.color_mode = QComboBox()
        self.color_mode.addItems(["Temperature", "Today's risk"])
        self.color_mode.setCursor(Qt.PointingHandCursor)
        set_base_style(self.color_mode, COMBO_STYLE)
        self.color_mode.currentTextChanged.connect(self.change_map_mode)
        body.addWidget(self.color_mode)

        body.addWidget(section_label("WEATHER DATA"))
        self.source_mode = QComboBox()
        self.source_mode.addItem("Live forecast (next 5 days)", None)
        for start, label in REPLAY_EVENTS:
            self.source_mode.addItem(f"Replay: {label}", start)
        self.source_mode.setCursor(Qt.PointingHandCursor)
        self.source_mode.setToolTip("Replay shows archived weather for a real past heat wave, so the "
                                    "warning flow can be demonstrated outside the heat season.")
        set_base_style(self.source_mode, COMBO_STYLE)
        self.source_mode.currentIndexChanged.connect(self.change_source)
        body.addWidget(self.source_mode)

        body.addSpacing(4)
        head = QHBoxLayout()
        head.addWidget(section_label("HEAT ALERTS"))
        head.addStretch()
        log_btn = QPushButton("Log")
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.setToolTip("Show alerts that have been sent")
        set_base_style(log_btn, f"QPushButton {{ background:transparent;color:$focus;border:none;"
                                f"font-size:{FS_SMALL}px;font-weight:800;padding:2px 4px; }}")
        log_btn.clicked.connect(lambda: AlertLogDialog(self).exec_())
        head.addWidget(log_btn)
        body.addLayout(head)
        self.alert_box = QVBoxLayout()
        self.alert_box.setSpacing(8)
        body.addLayout(self.alert_box)
        if self.user["role"] == "admin":
            self.notify_btn = QPushButton("Notify officers…")
            self.notify_btn.setCursor(Qt.PointingHandCursor)
            set_base_style(self.notify_btn,
                           f"QPushButton {{ background:$primary;color:$onPrimary;border:none;border-radius:10px;"
                           f"padding:10px;font-weight:700;font-size:{FS_BODY}px; }}"
                           f"QPushButton:hover {{ background:$primaryHover; }}")
            self.notify_btn.clicked.connect(self.notify_officers)
            body.addWidget(self.notify_btn)
        body.addWidget(muted_label(
            "Alerts follow the IMD heat-wave criteria (max temperature vs the local normal), coloured "
            "YELLOW / ORANGE / RED. WATCH = seen in one forecast update. WARNING = confirmed in "
            f"{alert_engine.CONFIRM_UPDATES} consecutive updates; officers are notified automatically."
        ))

        body.addSpacing(4)
        body.addWidget(section_label("PRIORITY DISTRICTS"))
        self.priority_box = QVBoxLayout()
        self.priority_box.setSpacing(6)
        body.addLayout(self.priority_box)
        body.addWidget(muted_label(
            "Ranked by relative risk over the next 3 days, hours of dangerous heat and "
            + ("response capacity." if self.capacities else
               "response capacity (add data/response_capacity.csv to include it).")
        ))

        body.addSpacing(4)
        body.addWidget(muted_label(
            "Prototype uses district boundaries. Production will use ward / zone boundaries "
            "for hyperlocal risk."
        ))
        body.addStretch()
        return self.left

    def _build_centre(self):
        centre = QFrame()
        centre.setObjectName("centre")
        set_base_style(centre, "QFrame#centre { background:$bg; } QLabel { background:transparent; }")
        layout = QVBoxLayout(centre)
        layout.setContentsMargins(22, 16, 22, 14)
        layout.setSpacing(12)

        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self.kpi_high = KpiTile("Heat-wave districts")
        self.kpi_hot = KpiTile("Hottest now")
        self.kpi_feels = KpiTile("Peak feels-like")
        self.kpi_pop = KpiTile("Population exposed")
        self.kpi_alerts = KpiTile("Alerts")
        for tile in (self.kpi_high, self.kpi_hot, self.kpi_feels, self.kpi_pop, self.kpi_alerts):
            kpis.addWidget(tile, 1)
        layout.addLayout(kpis)

        self.replay_banner = QLabel()
        self.replay_banner.setWordWrap(True)
        set_base_style(self.replay_banner, f"font-size:{FS_BODY}px;font-weight:700;color:$warnText;"
                                           f"background:$warnBg;border-radius:10px;padding:10px 14px;")
        self.replay_banner.hide()
        layout.addWidget(self.replay_banner)

        header = QHBoxLayout()
        title = QLabel(f"{STATE_NAME}  •  Heat Risk Map")
        set_base_style(title, f"font-size:{FS_TITLE}px;font-weight:800;color:$text;")
        self.map_hint = hint = QLabel("Point at a district for quick data  •  Click for full details")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        set_base_style(hint, f"font-size:{FS_BODY}px;color:$muted;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(hint)
        layout.addLayout(header)

        self.map = TamilNaduMap(self.census, self.select_item)
        layout.addWidget(self.map, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        selector = QVBoxLayout()
        selector.setSpacing(6)
        selector.addWidget(section_label("DISTRICT"))
        self.combo = QComboBox()
        self.combo.setCursor(Qt.PointingHandCursor)
        self.combo.setMinimumWidth(200)
        set_base_style(self.combo, COMBO_STYLE)
        self.combo.currentTextChanged.connect(self.select_from_combo)
        selector.addWidget(self.combo)
        bottom.addLayout(selector)

        legend_card = QFrame()
        legend_card.setObjectName("legendCard")
        set_base_style(legend_card, "QFrame#legendCard { background:$surface; border:1px solid $border; border-radius:12px; }")
        legend_layout = QVBoxLayout(legend_card)
        legend_layout.setContentsMargins(16, 10, 16, 8)
        self.legend = GradientLegend("Temperature")
        legend_layout.addWidget(self.legend)
        bottom.addWidget(legend_card, 1)
        layout.addLayout(bottom)
        return centre

    def install_shortcuts(self):
        for keys, delta in (("Ctrl+=", FONT_SCALE_STEP), ("Ctrl++", FONT_SCALE_STEP), ("Ctrl+-", -FONT_SCALE_STEP)):
            QShortcut(QKeySequence(keys), self,
                      activated=lambda d=delta: self.size_control.set_scale(font_scale() + d))
        QShortcut(QKeySequence("Ctrl+0"), self, activated=lambda: self.size_control.set_scale(1.0))
        QShortcut(QKeySequence("F5"), self, activated=lambda: self.load_weather(force=True))

    # ------------------------------------------------------------------ sizing
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.apply_breakpoints()

    def apply_breakpoints(self):
        """Adapt to the window width (logical px): wide, compact, narrow."""
        if not hasattr(self, "detail"):     # resize before the UI is built
            return
        width = self.width()
        compact, narrow = width < COMPACT_WIDTH, width < NARROW_WIDTH
        if narrow != self._narrow:          # only on crossing, so the ☰ button still works
            self._narrow = narrow
            self.left.set_expanded(not narrow)
            self.badge.setVisible(not narrow)
        if compact != self._compact:
            self._compact = compact
            self.subtitle.setVisible(not compact)
            self.map_hint.setVisible(not compact)
            self.theme_toggle.set_compact(compact)
            self.size_control.set_compact(compact)
            self.badge.setText(self.badge_short if compact else self.badge_full)
        base = RIGHT_PANEL_NARROW if narrow else RIGHT_PANEL_COMPACT if compact else RIGHT_PANEL_WIDTH
        self.detail.setFixedWidth(int(base * (1 + (font_scale() - 1) * 0.6)))

    def after_scale_change(self):
        self.size_control.sync()
        self.left.apply_width()
        self.legend.on_theme_changed()
        self.apply_breakpoints()

    # ------------------------------------------------------------------ data
    def prepare_locations(self):
        geo = load_geojson()
        self.locations = []
        for feature in geo.get("features", []):
            name = get_property(feature, "district", "District", "DISTRICT", "NAME_2", "name", "NAME")
            lat, lon = geometry_centroid(feature.get("geometry"))
            self.locations.append((name, lat, lon))
        self.demographics = {item.zone_name: item.metrics["demographic"] for item in self.map.zone_items}

        self.combo.blockSignals(True)
        self.combo.clear()
        for item in sorted(self.map.zone_items, key=lambda x: x.zone_name.lower()):
            self.combo.addItem(item.zone_name)
        self.combo.blockSignals(False)

        home = self.map.find(self.user.get("district", "")) if self.user.get("district") else None
        first = home or (self.map.find("Chennai") or (self.map.zone_items[0] if self.map.zone_items else None))
        if first:
            self.select_item(first, collapse_left=False)

    def load_weather(self, force=False):
        if self.worker is not None and self.worker.isRunning():
            self._reload_pending = True        # e.g. data source switched mid-download
            return
        self._reload_pending = False
        self.detail.refresh.setEnabled(False)
        self.detail.refresh.setText("Updating…")
        self.worker = WeatherWorker(self.locations, self.demographics, self.capacities, force, self.replay)
        self.worker.finished_data.connect(self.weather_ready)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _worker_finished(self):
        if getattr(self, "_reload_pending", False):
            self.load_weather(force=False)

    def weather_ready(self, results, info):
        if info.get("replay") != self.replay:     # user switched data source mid-download
            self._reload_pending = True
            return
        self.weather_info = info
        for item in self.map.zone_items:
            if item.zone_name in results:
                item.set_metrics(results[item.zone_name])
            elif info.get("replay"):              # replay could not be loaded – no stale numbers
                item.set_metrics(placeholder_metrics(item.metrics["demographic"]))
        self.detail.refresh.setEnabled(not self.replay)
        self.detail.refresh.setText("Replay – live refresh off" if self.replay else "Refresh live weather")

        zone_metrics = {i.zone_name: i.metrics for i in self.map.zone_items if i.metrics.get("loaded")}
        self.alerts, newly_confirmed = alert_engine.evaluate(zone_metrics, info)
        for alert in newly_confirmed:
            m = zone_metrics[alert["district"]]
            alert_engine.dispatch(alert, self.auth.recipients_for(alert["district"]),
                                  alert_engine.suggested_actions(m))

        self._update_kpis(zone_metrics)
        self._update_alert_list()
        self._update_priority_list(zone_metrics)
        self._update_status()

        fetched = datetime.fromtimestamp(info.get("fetched_at", time.time())).strftime("%H:%M")
        text = f"{info.get('source', '')}  •  data from {fetched}\nF5 to refresh"
        if info.get("source") == "DEMO":
            text = "OFFLINE – showing DEMO data (no internet)\nF5 to retry"
        if self.replay:
            label = dict(REPLAY_EVENTS).get(self.replay, self.replay)
            text = f"REPLAY – archived weather\n{label}"
            self.replay_banner.setText(
                f"Replay mode: archived weather for {label}, shown as if it were the forecast. "
                "Not live data – nothing is sent to officers. "
                + (f"({info['error']})" if info.get("error") else "Switch back under WEATHER DATA."))
        self.replay_banner.setVisible(bool(self.replay))
        self.updated_label.setText(text)
        if newly_confirmed:
            names = ", ".join(a["district"] for a in newly_confirmed)
            self.updated_label.setText(self.updated_label.text() + f"\nNew WARNING: {names}")

        if self.selected_item:
            self._show_detail(self.selected_item)

    # ------------------------------------------------------------------ side lists
    def _update_kpis(self, zm):
        if not zm:
            return
        total = len(self.map.zone_items)
        high = [n for n, m in zm.items() if m["imd"]["code"] != "GREEN"]
        worst = max((zm[n]["imd"]["code"] for n in high), key=code_index, default="GREEN")
        self.kpi_high.set(f"{len(high)} / {total}",
                          f"Next 5 days • highest IMD {worst}" if high else "None in the next 5 days",
                          risk_band_color(worst))
        hot_name, hot = max(zm.items(), key=lambda kv: kv[1]["temperature"])
        self.kpi_hot.set(f"{hot['temperature']:.1f}°C", hot_name, risk_band_color(hot["risk"]))
        best = None
        for name, m in zm.items():
            for day in m["forecast"]:
                if best is None or day["stress"] > best[1]["stress"]:
                    best = (name, day)
        if best:
            self.kpi_feels.set(f"{best[1]['stress']:.0f}°C", f"{best[0]} • {best[1]['date_text']}",
                               risk_band_color(best[1]["risk"]))
        pop = sum(zm[n]["demographic"].get("population", 0) for n in high)
        self.kpi_pop.set(format_population(pop) if pop else "0", "In heat-wave districts (Census 2011)",
                         risk_band_color(worst if pop else "GREEN"))
        warn = sum(1 for a in self.alerts if a["level"] == "WARNING")
        watch = len(self.alerts) - warn
        self.kpi_alerts.set(f"{warn} warning{'s' if warn != 1 else ''}", f"{watch} on watch",
                            risk_band_color(self.alerts[0]["colour"] if self.alerts else "GREEN"))

    def _update_alert_list(self):
        clear_layout(self.alert_box)
        if not self.alerts:
            self.alert_box.addWidget(muted_label("No heat wave forecast in the next 5 days."))
            return
        for alert in self.alerts[:8]:
            row = ClickableRow()
            row.row.addWidget(band_chip(alert["level"], alert["colour"]))
            text = QVBoxLayout()
            text.setSpacing(0)
            name = QLabel(alert["district"])
            set_base_style(name, f"font-size:{FS_BODY}px;font-weight:800;")
            when = QLabel(f"IMD {alert['colour']} • from {alert['day']}")
            set_base_style(when, f"font-size:{FS_SMALL}px;color:$muted;")
            text.addWidget(name)
            text.addWidget(when)
            row.row.addLayout(text, 1)
            row.clicked.connect(lambda n=alert["district"]: self.select_by_name(n))
            self.alert_box.addWidget(row)
        if len(self.alerts) > 8:
            self.alert_box.addWidget(muted_label(f"+ {len(self.alerts) - 8} more"))

    def _update_priority_list(self, zm):
        clear_layout(self.priority_box)
        ranked = sorted(zm.items(), key=lambda kv: (code_index(kv[1]["imd"]["code"]), kv[1]["priority"]),
                        reverse=True)[:8]
        for rank, (name, m) in enumerate(ranked, 1):
            row = ClickableRow()
            num = QLabel(str(rank))
            num.setFixedWidth(scaled(22))
            set_base_style(num, f"font-size:{FS_BODY}px;font-weight:800;color:$muted;")
            label = QLabel(name)
            set_base_style(label, f"font-size:{FS_BODY}px;font-weight:700;")
            score = QLabel(f"{m['priority']:.0f}")
            colour = risk_band_color(m["imd"]["code"] if m["imd"]["code"] != "GREEN" else
                                     (m["peak_band"] if m["peak_band"] != "—" else "LOW"))
            set_base_style(score, f"font-size:{FS_SMALL}px;font-weight:800;color:{contrast_text(colour)};"
                                  f"background:{colour};border-radius:7px;padding:3px 9px;")
            score.setToolTip(f"Priority score. IMD {m['imd']['code']}; highest heat-stress band: {m['peak_band']}")
            row.row.addWidget(num)
            row.row.addWidget(label, 1)
            row.row.addWidget(score)
            row.clicked.connect(lambda n=name: self.select_by_name(n))
            self.priority_box.addWidget(row)

    def _update_status(self):
        channels = alert_engine.gateway_status()
        gateway = ", ".join(channels) if channels else "alerts logged (SMS gateway not configured)"
        weather = ("Weather: REPLAY of archived Open-Meteo data" if self.replay else
                   "Weather: Open-Meteo, refreshed hourly")
        self.status.setText(
            f"{weather}   •   Thermal engine: {engine_name()}   •   "
            f"Heat waves: IMD criteria{'' if self.weather_info.get('normals') else ' (normals not loaded – 45 °C rule only)'}   •   "
            f"Population: Census 2011   •   Alerts: {gateway}   •   {APP_VERSION} – prototype scores"
        )

    # ------------------------------------------------------------------ selection
    def select_by_name(self, name):
        item = self.map.find(name)
        if item:
            self.select_item(item, collapse_left=False)

    def select_from_combo(self, name):
        self.select_by_name(name)

    def select_item(self, item, collapse_left=False):
        self.selected_item = item
        self.map.highlight(item)
        self._show_detail(item)
        index = self.combo.findText(item.zone_name)
        if index >= 0 and self.combo.currentIndex() != index:
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(index)
            self.combo.blockSignals(False)

    def _show_detail(self, item):
        alert = next((a for a in self.alerts if a["district"] == item.zone_name), None)
        self.detail.show_item(item, self.weather_info.get("source", ""), alert)

    def change_source(self, _index):
        self.replay = self.source_mode.currentData()
        self.load_weather(force=False)

    def change_map_mode(self, text):
        self.map.set_color_mode("temperature" if text == "Temperature" else "risk")
        self.legend.set_mode("Temperature" if text == "Temperature" else "Risk")

    # ------------------------------------------------------------------ actions
    def district_names(self):
        return [i.zone_name for i in self.map.zone_items]

    def open_access_manager(self):
        AccessManagerDialog(self.auth, self, self.district_names()).exec_()

    def notify_officers(self):
        if self.replay:
            QMessageBox.information(self, "Replay mode",
                                    "Alerts can't be sent while replaying past weather.\n\n"
                                    "Switch WEATHER DATA back to the live forecast first.")
            return
        warnings = [a for a in self.alerts if a["level"] == "WARNING"]
        targets = warnings
        if not warnings:
            if not self.selected_item or not self.selected_item.metrics.get("loaded"):
                return
            m = self.selected_item.metrics
            ask = QMessageBox.question(
                self, "No confirmed warnings",
                "There are no confirmed warnings right now.\n\nSend a manual advisory for "
                f"{self.selected_item.zone_name} ({m['risk']} heat stress today) to its officers?")
            if ask != QMessageBox.Yes:
                return
            targets = [{
                "district": self.selected_item.zone_name, "level": "ADVISORY", "risk": m["risk"],
                "day": "Today", "stress": m["today_peak_stress"], "model": m["stress_model"],
                "hours_danger": m["today_hours_danger"], "score": m["risk_score"],
            }]
        else:
            names = ", ".join(a["district"] for a in warnings)
            if QMessageBox.question(self, "Notify officers",
                                    f"Send heat warnings for: {names}?") != QMessageBox.Yes:
                return
        lines = []
        for alert in targets:
            m = self.map.find(alert["district"]).metrics
            results = alert_engine.dispatch(alert, self.auth.recipients_for(alert["district"]),
                                            alert_engine.suggested_actions(m))
            for label, channel, status in results:
                lines.append(f"{alert['district']}: {label} – {channel} – {status}")
        QMessageBox.information(self, "Alert dispatch", "\n".join(lines) or "Nothing was sent.")

    def sign_out(self):
        self._signed_out = True
        self.close()

    def closeEvent(self, event):
        self.refresh_timer.stop()
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(3000)
        event.accept()


def main():
    # Follow Windows display scaling exactly (125 %, 150 %, 175 %). Qt 5 otherwise
    # rounds it (150 % → 200 %), which made the app too big for smaller laptops.
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass                                  # Qt < 5.14
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)   # no "?" on dialogs
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    load_ui_settings()
    set_app_style(app, APP_STYLE)
    auth = AuthManager()

    while True:
        login = LoginDialog(auth)
        if login.exec_() != QDialog.Accepted:
            return
        window = MainWindow(login.user, auth)
        window.showMaximized()
        app.exec_()
        if not getattr(window, "_signed_out", False):
            break
    sys.exit(0)


if __name__ == "__main__":
    main()
