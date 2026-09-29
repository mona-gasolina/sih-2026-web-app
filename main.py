import sys
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QEvent, QThread, QTimer, pyqtSignal, QRectF
from PyQt5.QtGui import QColor, QPainter, QBrush, QLinearGradient, QFont, QFontMetrics, QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QPushButton, QScrollArea, QShortcut, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget, QMenu, QWidgetAction, QBoxLayout, QSizePolicy
)

import alerts as alert_engine
from auth import AuthManager
from config import (
    APP_TITLE, APP_SHORT, APP_VERSION, STATE_NAME, WINDOW_HEIGHT, WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, LEFT_PANEL_SHARE, LEFT_PANEL_MIN, LEFT_PANEL_MAX,
    RIGHT_PANEL_SHARE, RIGHT_PANEL_MIN, RIGHT_PANEL_MAX,
    REPLAY_EVENTS, WEATHER_CACHE_MINUTES, FONT_FAMILY,
    FS_SMALL, FS_LABEL, FS_BODY, FS_HEADING, FS_TITLE, FS_BRAND, FS_VALUE,
    FONT_SCALE_STEP, TEMP_GRADIENT_STOPS, RISK_GRADIENT_STOPS, band_label,
    set_base_style, set_app_style, load_ui_settings, font_scale, ui_scale, fit_text_to_screen, scaled, c,
    risk_band_color, contrast_text, temperature_gradient,
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
        self.vertical = False
        self.on_theme_changed()

    def set_vertical(self, vertical):
        """Vertical beside the map (tall screens use the width), horizontal below it."""
        self.vertical = vertical
        self.on_theme_changed()

    def on_theme_changed(self):
        s = ui_scale()
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        if self.vertical:
            self.setFixedWidth(scaled(118))
            self.setMinimumHeight(scaled(170))
        else:
            self.setFixedHeight(int(FS_LABEL * s + 10 + 20 + 8 + FS_SMALL * s + 8))
        self.updateGeometry()
        self.update()

    def _title(self):
        if self.mode == "Temperature":
            return "AIR TEMPERATURE NOW (°C)"
        return "TODAY'S RELATIVE RISK" + ("" if self.vertical else "  (0 = low, 100 = extreme)")

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def _stops(self):
        """(gradient stops as (0-1 position, colour), labels as (0-1 position, text))."""
        if self.mode == "Temperature":
            lo, hi = TEMP_GRADIENT_STOPS[0][0], TEMP_GRADIENT_STOPS[-1][0]
            stops = [((t - lo) / (hi - lo), colour) for t, colour in TEMP_GRADIENT_STOPS]
            labels = [((t - lo) / (hi - lo), f"{t:.0f}°") for t, _ in TEMP_GRADIENT_STOPS]
            labels[0], labels[-1] = (0.0, f"≤{lo:.0f}°"), (1.0, f"{hi:.0f}°+")
        else:
            stops = [(v / 100.0, colour) for v, colour in RISK_GRADIENT_STOPS]
            labels = [(v / 100.0, str(v)) for v, _ in RISK_GRADIENT_STOPS]
        return stops, labels

    def _paint_vertical(self, p, title_font, label_font):
        p.setFont(title_font)
        p.setPen(QColor(c("text")))
        title_rect = p.boundingRect(QRectF(0, 0, self.width(), 1000), Qt.TextWordWrap, self._title())
        p.drawText(QRectF(0, 0, self.width(), title_rect.height()), Qt.TextWordWrap, self._title())
        fm = QFontMetrics(label_font)
        bar = QRectF(2, title_rect.height() + 10 + fm.height() / 2, 20,
                     max(60, self.height() - title_rect.height() - 14 - fm.height()))
        stops, labels = self._stops()
        gradient = QLinearGradient(0, bar.bottom(), 0, bar.top())     # hot at the top
        for pos, colour in stops:
            gradient.setColorAt(pos, QColor(colour))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gradient))
        p.drawRoundedRect(bar, 8, 8)
        p.setFont(label_font)
        p.setPen(QColor(c("muted")))
        for pos, text in labels:
            y = bar.bottom() - pos * bar.height()
            p.drawText(QRectF(bar.right() + 8, y - fm.height() / 2, self.width() - bar.right() - 8, fm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, text)

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
        if self.vertical:
            self._paint_vertical(p, title_font, label_font)
            p.end()
            return

        p.setFont(title_font)
        p.setPen(QColor(c("text")))
        title_h = QFontMetrics(title_font).height()
        p.drawText(QRectF(0, 0, width, title_h), Qt.AlignLeft | Qt.AlignVCenter, self._title())

        bar = QRectF(2, title_h + 8, max(80, width - 4), 20)
        gradient = QLinearGradient(bar.left(), 0, bar.right(), 0)
        stops, labels = self._stops()
        for pos, colour in stops:
            gradient.setColorAt(pos, QColor(colour))
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
        self.caption = ElidedLabel()
        self.caption.set_full_text(caption.upper())
        self.value = QLabel("—")
        self.sub = QLabel("Loading…")
        self.sub.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
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
        self.base_width = LEFT_PANEL_MAX
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
        self.body_layout.setContentsMargins(0, 8, 10, 0)
        self.body_layout.setSpacing(12)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)
        self.apply_width()

    def apply_width(self):
        self.setFixedWidth(self.base_width if self.expanded else self.COLLAPSED_WIDTH)

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


class Page(QWidget):
    """Dashboard page. Wrapped labels must not make the scroll area think the
    page needs more height than its minimum, or the whole page scrolls."""

    def heightForWidth(self, width):
        return -1


class ElidedLabel(QLabel):
    """One-line label that shortens itself with "…"; the full text is the tooltip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.full_text = ""
        self.setMinimumWidth(1)

    def set_full_text(self, text, tooltip=None):
        self.full_text = text
        self.setToolTip(tooltip or text)
        self._refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def on_theme_changed(self):
        self._refresh()

    def _refresh(self):
        room = max(10, self.contentsRect().width())
        self.setText(self.fontMetrics().elidedText(self.full_text, Qt.ElideRight, room))


def make_combo(parent_style=None):
    """Combo box that can shrink (long items are shortened) instead of widening its panel."""
    combo = QComboBox()
    combo.setCursor(Qt.PointingHandCursor)
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(8)
    set_base_style(combo, parent_style or COMBO_STYLE)
    return combo


def info_label(text, details):
    """Short muted line with an ⓘ; the explanation is shown on hover."""
    label = QLabel(f"ⓘ  {text}")
    label.setWordWrap(True)
    label.setToolTip(details)
    label.setCursor(Qt.WhatsThisCursor)
    set_base_style(label, f"font-size:{FS_SMALL}px;color:$subtle;")
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
    # (log field, column title). "Logged" is when the alert was created;
    # "Heat expected from" is the first forecast heat-wave day it was about.
    COLUMNS = [("timestamp", "Logged"), ("district", "District"), ("level", "Alert"),
               ("code", "Colour"), ("heat_from", "Heat expected from"), ("recipient", "Sent to"),
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
            f"Alerts go out by {' and '.join(channels)}." if channels else
            "Text messages aren't set up on this computer yet, so alerts are saved here instead."
        )
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        if not channels:
            sub.setToolTip("To send real SMS/WhatsApp messages, set TWILIO_ACCOUNT_SID, "
                           "TWILIO_AUTH_TOKEN and TWILIO_FROM (see README).")
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
        header.setSectionResizeMode(5, QHeaderView.Stretch)      # "Sent to" takes the spare width
        for r, row in enumerate(self.rows):
            for col, (key, _) in enumerate(self.COLUMNS):
                value = row.get(key, "")
                if key == "timestamp":
                    value = _log_time(value)
                elif key in ("level", "code"):
                    value = value.title()
                table.setItem(r, col, QTableWidgetItem(value))
        table.itemSelectionChanged.connect(
            lambda: self._show_message(table.currentRow()))
        layout.addWidget(table, 1)

        self.message = QLabel("No alerts yet." if not self.rows else
                              "Click a row to see the message that was sent.")
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
            self.message.setText("Message:  " + (self.rows[row].get("message", "") or "(none saved)"))


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
        self._fitting = False
        self._auto_collapsed = None         # side panel closed to make room
        self._height_on = frozenset()

        self.setWindowTitle(f"{APP_SHORT} • {STATE_NAME}")
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        fit_to_screen(self, WINDOW_WIDTH, WINDOW_HEIGHT)
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
        self.page = Page()
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
        self.detail = DetailPanel()
        row.addWidget(self.detail)
        root.addLayout(row, 1)

        self.status = ElidedLabel()
        self.status.setAlignment(Qt.AlignCenter)
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
        self.top_bar = top = QFrame()
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

        self.updated_label = QLabel("Getting the forecast…")
        self.updated_label.setWordWrap(True)
        set_base_style(self.updated_label, f"font-size:{FS_SMALL}px;color:$muted;")
        self.updated_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.updated_label)
        self.refresh_btn = QPushButton("⟳  Refresh")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setToolTip("Get the latest forecast now (F5 or Ctrl+R). It also updates by itself every hour.")
        set_base_style(self.refresh_btn, f"QPushButton {{ background:$surface2;color:$text;border:1px solid $border;"
                                         f"border-radius:12px;padding:9px 14px;font-weight:700;font-size:{FS_SMALL + 1}px; }}"
                                         f"QPushButton:hover {{ background:$chip;border-color:$borderStrong; }}"
                                         f"QPushButton:disabled {{ color:$subtle; }}")
        self.refresh_btn.clicked.connect(lambda: self.load_weather(force=True))
        layout.addWidget(self.refresh_btn, 0, Qt.AlignVCenter)

        if self.user["role"] == "admin":
            self.manage_btn = manage = QPushButton("Manage Access")
            manage.setCursor(Qt.PointingHandCursor)
            set_base_style(manage, f"QPushButton {{ background:$primary;color:$onPrimary;border:none;"
                                   f"border-radius:11px;padding:11px 16px;font-weight:700;font-size:{FS_BODY}px; }}"
                                   f"QPushButton:hover {{ background:$primaryHover; }}")
            manage.clicked.connect(self.open_access_manager)
            layout.addWidget(manage, 0, Qt.AlignVCenter)

        layout.addWidget(self._build_user_menu(), 0, Qt.AlignVCenter)
        return top

    def _build_user_menu(self):
        """Name button whose menu holds display settings and sign-out."""
        who = self.user.get("full_name") or self.user["username"]
        role = "System Admin" if self.user["role"] == "admin" else "City Administrator"
        where = self.user.get("district") or self.user.get("city") or STATE_NAME
        initials = "".join(part[0] for part in who.split()[:2]).upper() or "☰"
        self.user_labels = {"full": f"{who}\n{role} • {where}", "short": who, "tiny": initials}
        self.user_btn = btn = QToolButton()
        btn.setText(self.user_labels["full"])
        btn.setToolTip(f"{who} – {role}, {where}\nDisplay settings and sign out")
        btn.setAccessibleName("Account and display settings")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setPopupMode(QToolButton.InstantPopup)
        set_base_style(btn, f"QToolButton {{ font-size:{FS_SMALL}px;font-weight:700;color:$text;background:$chip;"
                            f"border:1px solid $border;border-radius:10px;padding:7px 28px 7px 12px; }}"
                            f"QToolButton:hover {{ border-color:$borderStrong; }}"
                            f"QToolButton::menu-indicator {{ subcontrol-position:right center; right:6px; }}")

        menu = QMenu(btn)
        set_base_style(menu, f"QMenu {{ background:$surface;border:1px solid $border;border-radius:10px;padding:6px; }}"
                             f"QMenu::item {{ color:$text;font-size:{FS_BODY}px;font-weight:700;"
                             f"padding:9px 18px;border-radius:8px; }}"
                             f"QMenu::item:selected {{ background:$chip; }}"
                             f"QMenu::separator {{ height:1px;background:$border;margin:6px 8px; }}")
        panel = QFrame()
        panel.setObjectName("menuPanel")
        set_base_style(panel, f"QFrame#menuPanel {{ background:transparent; }}"
                              f"QLabel {{ background:transparent;color:$text; }}")
        box = QVBoxLayout(panel)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(10)
        name = QLabel(who)
        set_base_style(name, f"font-size:{FS_BODY}px;font-weight:800;")
        detail = QLabel(f"{role} • {where}")
        set_base_style(detail, f"font-size:{FS_SMALL}px;color:$muted;")
        box.addWidget(name)
        box.addWidget(detail)
        self.theme_toggle = ThemeToggle()
        box.addWidget(self.theme_toggle)
        self.size_control = TextSizeControl()
        self.size_control.changed.connect(lambda _: self.after_scale_change())
        box.addWidget(self.size_control)
        panel_action = QWidgetAction(menu)
        panel_action.setDefaultWidget(panel)
        menu.addAction(panel_action)
        menu.addSeparator()
        menu.addAction("Sign out", self.sign_out)
        btn.setMenu(menu)
        return btn

    def _build_left_panel(self):
        self.left = CollapsiblePanel("OVERVIEW")
        body = self.left.body_layout

        body.addWidget(section_label("MAP LAYER"))
        self.color_mode = make_combo()
        self.color_mode.addItems(["Temperature", "Today's risk"])
        self.color_mode.currentTextChanged.connect(self.change_map_mode)
        body.addWidget(self.color_mode)

        body.addWidget(section_label("WEATHER DATA"))
        self.source_mode = make_combo()
        self.source_mode.addItem("Live forecast", None)
        for start, label in REPLAY_EVENTS:
            self.source_mode.addItem(f"Replay: {start[:4]} heat wave", start)
            self.source_mode.setItemData(self.source_mode.count() - 1, label, Qt.ToolTipRole)
        self.source_mode.setToolTip("Live = next 5 days. Replay = archived weather for a real past heat "
                                    "wave, to show the warning flow outside the heat season.")
        self.source_mode.currentIndexChanged.connect(self.change_source)
        body.addWidget(self.source_mode)

        body.addSpacing(4)
        head = QHBoxLayout()
        head.addWidget(section_label("HEAT ALERTS"))
        head.addStretch()
        log_btn = QPushButton("View log")
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.setToolTip("Alerts that have been sent or logged")
        set_base_style(log_btn, f"QPushButton {{ background:$chip;color:$text;border:1px solid $border;"
                                f"border-radius:8px;font-size:{FS_SMALL}px;font-weight:800;padding:4px 10px; }}"
                                f"QPushButton:hover {{ border-color:$borderStrong; }}")
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
        body.addWidget(info_label(
            "How alerts work",
            "We use IMD's heat-wave rules: how far the day's maximum is above the usual for that date.\n"
            "Watch – a heat wave showed up in one forecast.\n"
            f"Warning – it's still there {alert_engine.MIN_UPDATE_GAP_HOURS}+ hours later and another "
            "forecast model agrees. Officers are then messaged once."
        ))

        body.addSpacing(4)
        self.priority_title = section_label("PRIORITY DISTRICTS")
        body.addWidget(self.priority_title)
        self.priority_note = muted_label("")
        self.priority_note.hide()
        body.addWidget(self.priority_note)
        self.priority_box = QVBoxLayout()
        self.priority_box.setSpacing(6)
        body.addLayout(self.priority_box)
        body.addWidget(info_label(
            "How districts are ranked",
            "Heat-wave colour first, then risk over the next 3 days, hours of very strong heat"
            + (" and response capacity." if self.capacities else ".")
            + "\nDistricts for now – wards and zones later."
        ))
        body.addStretch()
        return self.left

    def _build_centre(self):
        centre = QFrame()
        centre.setObjectName("centre")
        set_base_style(centre, "QFrame#centre { background:$bg; } QLabel { background:transparent; }")
        self.centre_layout = layout = QVBoxLayout(centre)
        layout.setContentsMargins(22, 16, 22, 14)
        layout.setSpacing(12)

        self.kpi_row = kpis = QGridLayout()
        kpis.setSpacing(12)
        self.kpi_high = KpiTile("Heat waves")
        self.kpi_hot = KpiTile("Hottest now")
        self.kpi_feels = KpiTile("Feels like (max)")
        self.kpi_pop = KpiTile("People exposed")
        self.kpi_alerts = KpiTile("Alerts")
        self.kpi_tiles = (self.kpi_high, self.kpi_hot, self.kpi_feels, self.kpi_pop, self.kpi_alerts)
        self._kpi_columns = None
        self._flow_kpis(len(self.kpi_tiles))
        layout.addLayout(kpis)

        self.replay_banner = QLabel()
        self.replay_banner.setWordWrap(True)
        set_base_style(self.replay_banner, f"font-size:{FS_BODY}px;font-weight:700;color:$warnText;"
                                           f"background:$warnBg;border-radius:10px;padding:10px 14px;")
        self.replay_banner.hide()
        layout.addWidget(self.replay_banner)

        header = QHBoxLayout()
        self.map_title = title = QLabel(f"{STATE_NAME}  •  Heat Risk Map")
        set_base_style(title, f"font-size:{FS_TITLE}px;font-weight:800;color:$text;")
        self.map_hint = hint = ElidedLabel()
        hint.set_full_text("Hover a district for a quick look · click it for details")
        hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        set_base_style(hint, f"font-size:{FS_BODY}px;color:$muted;")
        header.addWidget(title)
        header.addWidget(hint, 1)
        layout.addLayout(header)

        # The map, plus the district picker and legend, which sit beside the map
        # when that leaves it more room (wide windows) and below it otherwise.
        self.map_area = QWidget()
        self.map_grid = QGridLayout(self.map_area)
        self.map_grid.setContentsMargins(0, 0, 0, 0)
        self.map_grid.setSpacing(14)
        self.map = TamilNaduMap(self.census, self.select_item)
        self.map_grid.addWidget(self.map, 0, 0)
        layout.addWidget(self.map_area, 1)

        self.map_controls = QWidget()
        self.controls_box = bottom = QBoxLayout(QBoxLayout.LeftToRight, self.map_controls)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(14)
        self.selector_box = selector = QWidget()
        selector_layout = QVBoxLayout(selector)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setSpacing(6)
        selector_layout.addWidget(section_label("DISTRICT"))
        self.combo = make_combo()
        self.combo.setMinimumWidth(170)
        self.combo.currentTextChanged.connect(self.select_from_combo)
        selector_layout.addWidget(self.combo)
        bottom.addWidget(selector, 0, Qt.AlignTop)

        self.legend_card = legend_card = QFrame()
        legend_card.setObjectName("legendCard")
        set_base_style(legend_card, "QFrame#legendCard { background:$surface; border:1px solid $border; border-radius:12px; }")
        legend_layout = QVBoxLayout(legend_card)
        legend_layout.setContentsMargins(16, 10, 16, 8)
        self.legend = GradientLegend("Temperature")
        legend_layout.addWidget(self.legend)
        bottom.addWidget(legend_card, 1)
        self._legend_beside = None
        self._place_map_controls(False)
        return centre

    def install_shortcuts(self):
        for keys, delta in (("Ctrl+=", FONT_SCALE_STEP), ("Ctrl++", FONT_SCALE_STEP), ("Ctrl+-", -FONT_SCALE_STEP)):
            QShortcut(QKeySequence(keys), self,
                      activated=lambda d=delta: self.size_control.set_scale(font_scale() + d))
        QShortcut(QKeySequence("Ctrl+0"), self, activated=lambda: self.size_control.set_scale(1.0))
        for keys in ("F5", "Ctrl+R"):    # many laptops need Fn for F5, so Ctrl+R works too
            QShortcut(QKeySequence(keys), self, activated=lambda: self.load_weather(force=True))

    # ------------------------------------------------------------------ sizing
    # Nothing here assumes a particular screen. Side panels take a share of the
    # window; then optional details are dropped one step at a time, measuring
    # after each, until the dashboard fits. Only past the last step does the
    # page scroll. Text size already follows the screen (fit_text_to_screen).
    WIDTH_STEPS = ("short_name", "no_subtitle", "collapse_side", "tight", "icon_buttons",
                   "initials", "min_right", "kpis_two_rows")
    HEIGHT_STEPS = ("no_map_heading", "tight_vertical", "short_map", "no_kpi_notes")

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not getattr(self, "_screen_hooked", False):
            self._screen_hooked = True
            handle.screenChanged.connect(self.on_screen_changed)
            self.on_screen_changed(handle.screen())

    def on_screen_changed(self, screen):
        """Moved to another monitor (or its scaling changed): re-fit text and layout."""
        if fit_text_to_screen(screen):
            self.after_scale_change()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_layout()

    def fit_layout(self):
        if not hasattr(self, "detail") or self._fitting:    # not built yet / already fitting
            return
        self._fitting = True
        try:
            room = self.scroll.maximumViewportSize()
            text = 1 + (ui_scale() - 1) * 0.6               # bigger text needs wider panels
            share = lambda f, lo, hi: int(max(lo, min(hi, room.width() * f)) * text)
            self.left.base_width = share(LEFT_PANEL_SHARE, LEFT_PANEL_MIN, LEFT_PANEL_MAX)
            self._right_width = share(RIGHT_PANEL_SHARE, RIGHT_PANEL_MIN, RIGHT_PANEL_MAX)
            self._right_min = int(RIGHT_PANEL_MIN * text)
            self.left.apply_width()

            allow_beside = True
            for _ in range(3):              # again if the legend moved, since that changes what fits
                self._apply_height_steps(set())
                for level in range(len(self.WIDTH_STEPS) + 1):
                    self._apply_width_steps(set(self.WIDTH_STEPS[:level]))
                    if self._needed().width() <= room.width():
                        break
                for level in range(len(self.HEIGHT_STEPS) + 1):
                    self._apply_height_steps(set(self.HEIGHT_STEPS[:level]))
                    if self._needed().height() <= room.height():
                        break
                need = self._needed()
                if self._legend_beside and (need.width() > room.width() or need.height() > room.height()):
                    allow_beside = False    # beside only when it still fits without scrolling
                if not self._place_map_controls(allow_beside and self._legend_fits_beside()):
                    break
        finally:
            self._fitting = False

    def _map_scale(self, width, height):
        rect = self.map.scene.sceneRect()
        if rect.width() <= 0 or rect.height() <= 0 or width <= 0 or height <= 0:
            return 0
        return min(width / rect.width(), height / rect.height())

    def _legend_fits_beside(self):
        """True when the map ends up bigger with the picker and legend beside it."""
        area = self.map_area.size()
        spacing = self.map_grid.spacing()
        if self._legend_beside:
            side_w = self.map_controls.width() + spacing
            region_w, region_h = area.width(), area.height()
            below_h = self.selector_box.sizeHint().height() + spacing + 30
        else:
            side_w = max(self.combo.minimumSizeHint().width(), scaled(150)) + 34 + spacing
            region_w, region_h = area.width(), area.height() + self.map_controls.height() + spacing
            below_h = self.map_controls.height() + spacing
        beside = self._map_scale(region_w - side_w, region_h)
        below = self._map_scale(region_w, region_h - below_h)
        margin = 1.04 if self._legend_beside else 0.96         # hysteresis: don't flip back and forth
        return beside * margin > below

    def _place_map_controls(self, beside):
        """Returns True if the placement changed."""
        if beside == self._legend_beside:
            return False
        self._legend_beside = beside
        self.map_grid.removeWidget(self.map_controls)
        self.controls_box.setDirection(QBoxLayout.TopToBottom if beside else QBoxLayout.LeftToRight)
        self.controls_box.setAlignment(self.selector_box, Qt.AlignTop)
        self.legend.set_vertical(beside)
        self.legend_card.setSizePolicy(QSizePolicy.Preferred,
                                       QSizePolicy.Expanding if beside else QSizePolicy.Preferred)
        if beside:
            self.map_controls.setFixedWidth(max(self.combo.minimumSizeHint().width(), scaled(150)) + 34)
            self.map_grid.addWidget(self.map_controls, 0, 1)
            self.map_grid.setColumnStretch(0, 1)
        else:
            self.map_controls.setMinimumWidth(0)
            self.map_controls.setMaximumWidth(16777215)
            self.map_grid.addWidget(self.map_controls, 1, 0)
        return True

    def _needed(self):
        # Child changes reach the page's size hint through queued layout
        # requests; handle them now so each step is measured straight away.
        for _ in range(4):                  # one pass per nesting level
            QApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        return self.page.minimumSizeHint()

    def _apply_width_steps(self, on):
        self.user_btn.setText(self.user_labels["tiny" if "initials" in on else
                                                "short" if "short_name" in on else "full"])
        self._wide_details = "no_subtitle" not in on
        self.subtitle.setVisible(self._wide_details)
        self.map_hint.setVisible(self._wide_details and "no_map_heading" not in self._height_on)

        collapse = "collapse_side" in on          # only act on a change, so ☰ still works
        if collapse != self._auto_collapsed:
            self._auto_collapsed = collapse
            self.left.set_expanded(not collapse)

        tight = "tight" in on
        top = self.top_bar.layout()
        m = top.contentsMargins()
        top.setContentsMargins(14 if tight else 24, m.top(), 14 if tight else 24, m.bottom())
        top.setSpacing(8 if tight else 14)
        pad = 12 if tight else 22
        m = self.centre_layout.contentsMargins()
        self.centre_layout.setContentsMargins(pad, m.top(), pad, m.bottom())
        self.kpi_row.setSpacing(8 if tight else 12)

        self._icon_buttons = "icon_buttons" in on
        self._update_refresh_label()
        if hasattr(self, "manage_btn"):
            self.manage_btn.setText("Access" if self._icon_buttons else "Manage Access")
        self.detail.setFixedWidth(self._right_min if "min_right" in on else self._right_width)
        self._flow_kpis(3 if "kpis_two_rows" in on else len(self.kpi_tiles))

    def _update_refresh_label(self):
        if self.worker is not None and self.worker.isRunning():
            self.refresh_btn.setText("…" if getattr(self, "_icon_buttons", False) else "Updating…")
        else:
            self.refresh_btn.setText("⟳" if getattr(self, "_icon_buttons", False) else "⟳  Refresh")

    def _apply_height_steps(self, on):
        self._height_on = on
        heading = "no_map_heading" not in on
        self.map_title.setVisible(heading)
        self.map_hint.setVisible(heading and getattr(self, "_wide_details", True))
        tight = "tight_vertical" in on
        top = self.top_bar.layout()
        m = top.contentsMargins()
        top.setContentsMargins(m.left(), 8 if tight else 12, m.right(), 8 if tight else 12)
        m = self.centre_layout.contentsMargins()
        self.centre_layout.setContentsMargins(m.left(), 8 if tight else 16, m.right(), 8 if tight else 14)
        self.centre_layout.setSpacing(8 if tight else 12)
        self.map.setMinimumHeight(150 if "short_map" in on else 220)
        for tile in self.kpi_tiles:
            tile.sub.setVisible("no_kpi_notes" not in on)

    def _flow_kpis(self, columns):
        """One row of tiles, or two rows when the centre is very narrow."""
        if columns == self._kpi_columns:
            return
        self._kpi_columns = columns
        for tile in self.kpi_tiles:
            self.kpi_row.removeWidget(tile)
        for col in range(len(self.kpi_tiles)):
            self.kpi_row.setColumnStretch(col, 1 if col < columns else 0)
        for i, tile in enumerate(self.kpi_tiles):
            self.kpi_row.addWidget(tile, i // columns, i % columns)

    def after_scale_change(self):
        self.size_control.sync()
        self.legend.on_theme_changed()
        self.fit_layout()

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
        self.refresh_btn.setEnabled(False)
        self.worker = WeatherWorker(self.locations, self.demographics, self.capacities, force, self.replay)
        self.worker.finished_data.connect(self.weather_ready)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        self._update_refresh_label()

    def _worker_finished(self):
        self._update_refresh_label()
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
        self.refresh_btn.setEnabled(not self.replay)

        zone_metrics = {i.zone_name: i.metrics for i in self.map.zone_items if i.metrics.get("loaded")}
        self.alerts, newly_confirmed = alert_engine.evaluate(zone_metrics, info)
        for alert in newly_confirmed:
            m = zone_metrics[alert["district"]]
            alert_engine.dispatch(alert, self.auth.recipients_for(alert["district"]),
                                  alert_engine.suggested_actions(m, alert))

        self._update_kpis(zone_metrics)
        self._update_alert_list()
        self._update_priority_list(zone_metrics)
        self._update_status()

        fetched = datetime.fromtimestamp(info.get("fetched_at", time.time())).strftime("%H:%M")
        text = f"Forecast updated {fetched}"
        tip = ("Weather from Open-Meteo, which combines forecasts from national weather services "
               "(ECMWF, GFS, ICON and others). It updates by itself every hour.")
        if info.get("source") == "DEMO":
            text, tip = "Offline – showing sample data", f"No internet connection: {info.get('error', '')}"
        elif "offline" in info.get("source", ""):
            text = f"Offline – forecast from {fetched}"
        if self.replay:
            label = dict(REPLAY_EVENTS).get(self.replay, self.replay)
            text, tip = f"Replay: {label}", "Past weather, shown as if it were the forecast."
            self.replay_banner.setText(
                f"Replaying the {label} – past weather, not a live forecast. Nothing is sent to officers."
                + (f" ({info['error']})" if info.get("error") else ""))
            self.replay_banner.setToolTip("Past weather shown as if it were the forecast. "
                                          "Switch back under WEATHER DATA in the side panel.")
        self.replay_banner.setVisible(bool(self.replay))
        self.updated_label.setText(text)
        self.updated_label.setToolTip(tip)
        if newly_confirmed:
            names = ", ".join(a["district"] for a in newly_confirmed)
            self.updated_label.setText(text + f"\nNew warning: {names}")

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
                          f"districts · worst: {worst.lower()} alert" if high else "districts, next 5 days",
                          risk_band_color(worst))
        hot_name, hot = max(zm.items(), key=lambda kv: kv[1]["temperature"])
        self.kpi_hot.set(f"{hot['temperature']:.0f}°C", hot_name, temperature_gradient(hot["temperature"])[0])
        best = None
        for name, m in zm.items():
            for day in m["forecast"]:
                if best is None or day["stress"] > best[1]["stress"]:
                    best = (name, day)
        if best:
            self.kpi_feels.set(f"{best[1]['stress']:.0f}°C", f"{best[0]} • {best[1]['date_text']}",
                               temperature_gradient(best[1]["stress"] - 4)[0])
        pop = sum(zm[n]["demographic"].get("population", 0) for n in high)
        self.kpi_pop.set(format_population(pop) if pop else "0", "in heat-wave districts",
                         risk_band_color(worst if pop else "GREEN"))
        warn = sum(1 for a in self.alerts if a["level"] == "WARNING")
        watch = len(self.alerts) - warn
        self.kpi_alerts.set(f"{warn} warning{'s' if warn != 1 else ''}", f"{watch} on watch",
                            risk_band_color(self.alerts[0]["colour"] if self.alerts else "GREEN"))

    def _update_alert_list(self):
        clear_layout(self.alert_box)
        if not self.alerts:
            self.alert_box.addWidget(muted_label("No heat wave expected in the next 5 days."))
            return
        for alert in self.alerts[:8]:
            row = ClickableRow()
            text = QVBoxLayout()
            text.setSpacing(0)
            name = QLabel(alert["district"])
            name.setWordWrap(True)
            set_base_style(name, f"font-size:{FS_BODY}px;font-weight:800;")
            when = QLabel(f"{alert['colour'].title()} alert · from {alert['day']}")
            when.setWordWrap(True)
            set_base_style(when, f"font-size:{FS_SMALL}px;color:$muted;")
            text.addWidget(name)
            text.addWidget(when)
            row.row.addLayout(text, 1)
            row.row.addWidget(band_chip(alert["level"].title(), alert["colour"]), 0, Qt.AlignTop)
            row.clicked.connect(lambda n=alert["district"]: self.select_by_name(n))
            self.alert_box.addWidget(row)
        if len(self.alerts) > 8:
            self.alert_box.addWidget(muted_label(f"+ {len(self.alerts) - 8} more"))

    def _update_priority_list(self, zm):
        """Heat-wave districts first, in colour. With no heat wave anywhere the list is
        only for awareness, so it is titled and coloured to say no action is needed."""
        clear_layout(self.priority_box)
        ranked = sorted(zm.items(), key=lambda kv: (code_index(kv[1]["imd"]["code"]), kv[1]["priority"]),
                        reverse=True)[:8]
        any_heat_wave = any(m["imd"]["code"] != "GREEN" for m in zm.values())
        self.priority_title.setText("PRIORITY DISTRICTS" if any_heat_wave else "HIGHEST HEAT STRESS")
        self.priority_note.setText("No heat wave expected – for awareness only, no action needed.")
        self.priority_note.setVisible(bool(zm) and not any_heat_wave)
        for rank, (name, m) in enumerate(ranked, 1):
            row = ClickableRow()
            num = QLabel(str(rank))
            num.setFixedWidth(scaled(22))
            set_base_style(num, f"font-size:{FS_BODY}px;font-weight:800;color:$muted;")
            label = QLabel(name)
            set_base_style(label, f"font-size:{FS_BODY}px;font-weight:700;")
            score = QLabel(f"{m['priority']:.0f}")
            if m["imd"]["code"] != "GREEN":
                colour = risk_band_color(m["imd"]["code"])
                chip = f"color:{contrast_text(colour)};background:{colour};"
            else:
                chip = "color:$text;background:$chip;"
            set_base_style(score, f"font-size:{FS_SMALL}px;font-weight:800;{chip}border-radius:7px;padding:3px 9px;")
            score.setToolTip(f"Priority {m['priority']:.0f}/100 – hottest day this week: "
                             f"{band_label(m['peak_band']).lower()}")
            row.row.addWidget(num)
            row.row.addWidget(label, 1)
            row.row.addWidget(score)
            row.clicked.connect(lambda n=name: self.select_by_name(n))
            self.priority_box.addWidget(row)

    def _update_status(self):
        channels = alert_engine.gateway_status()
        alerts_text = (f"alerts by {' and '.join(channels)}" if channels else
                       "text alerts not set up – saved to the log")
        weather = "past weather (replay)" if self.replay else "forecast updates hourly"
        usual = "" if self.weather_info.get("normals") else " (usual temperatures not loaded)"
        self.status.set_full_text(
            f"{weather.capitalize()}   ·   {alerts_text.capitalize()}   ·   ⓘ About the data",
            f"About the data\n"
            f"• Weather: Open-Meteo – {weather}\n"
            f"• 'Feels like' = UTCI (sun, humidity, wind and heat from the ground)\n"
            f"• Heat waves = IMD rules{usual}\n"
            f"• Population = Census 2011\n"
            f"• {alerts_text.capitalize()}\n"
            f"• {APP_VERSION}",
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
                f"{self.selected_item.zone_name} ({band_label(m['risk']).lower()} today) to its officers?")
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
                                            alert_engine.suggested_actions(m, alert))
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
    fit_text_to_screen(app.primaryScreen())     # text sized for this screen, before login
    set_app_style(app, APP_STYLE)
    auth = AuthManager()

    while True:
        login = LoginDialog(auth)
        if login.exec_() != QDialog.Accepted:
            return
        window = MainWindow(login.user, auth)
        window.showMaximized()
        window.raise_()                 # in front, not behind whatever had focus before sign-in
        window.activateWindow()
        app.exec_()
        if not getattr(window, "_signed_out", False):
            break
    sys.exit(0)


if __name__ == "__main__":
    main()
