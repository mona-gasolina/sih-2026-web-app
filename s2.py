import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QBrush
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from pythermalcomfort.models import utci, solar_gain
    PYTHERMALCOMFORT_AVAILABLE = True
except ImportError:
    PYTHERMALCOMFORT_AVAILABLE = False


# ============================================================
# CONFIGURATION
# ============================================================

APP_TITLE = "EXTREME HEAT EARLY WARNING"
STATE_NAME = "Tamil Nadu"

# Public state GeoJSON containing Tamil Nadu with internal
# district-level boundaries. We use those boundaries as
# temporary "prototype zones" until actual ward GeoJSON is added.
MAP_URL = (
    "https://cdn.jsdelivr.net/gh/udit-001/india-maps-data@2884453/"
    "geojson/states/tamil-nadu.geojson"
)

DATA_DIR = Path(__file__).resolve().parent / "data"
MAP_FILE = DATA_DIR / "tamil_nadu.geojson"

WINDOW_WIDTH = 1450
WINDOW_HEIGHT = 820


# ============================================================
# PROTOTYPE DATA
# ============================================================

# These are DEMO environmental values only.
# They are not live weather observations.
# Replace them later with ward-level weather/API data.
DEMO_WEATHER = {
    "Chennai":      (38.0, 72.0, 2.1, 760.0),
    "Kancheepuram": (37.0, 68.0, 2.4, 720.0),
    "Tiruvallur":   (37.5, 70.0, 2.0, 750.0),
    "Vellore":      (39.0, 55.0, 1.7, 820.0),
    "Tirupattur":   (38.5, 58.0, 1.8, 810.0),
    "Ranipet":      (38.0, 60.0, 1.9, 790.0),
    "Krishnagiri":  (36.0, 52.0, 2.5, 780.0),
    "Dharmapuri":   (37.0, 50.0, 2.3, 800.0),
    "Salem":        (38.0, 56.0, 2.0, 830.0),
    "Namakkal":     (37.5, 58.0, 2.2, 840.0),
    "Erode":        (37.0, 54.0, 2.4, 850.0),
    "Tiruppur":     (38.0, 60.0, 2.0, 860.0),
    "Coimbatore":   (36.0, 62.0, 3.0, 780.0),
    "Nilgiris":     (27.0, 72.0, 2.7, 650.0),
    "Dindigul":     (37.0, 58.0, 2.5, 820.0),
    "Madurai":      (39.0, 55.0, 2.1, 870.0),
    "Theni":        (36.0, 60.0, 2.8, 780.0),
    "Virudhunagar": (38.0, 58.0, 2.0, 900.0),
    "Sivaganga":    (39.0, 60.0, 1.9, 890.0),
    "Ramanathapuram": (38.0, 72.0, 2.8, 820.0),
    "Pudukkottai":  (37.0, 67.0, 2.3, 850.0),
    "Thanjavur":    (37.0, 75.0, 2.7, 800.0),
    "Tiruvarur":    (36.5, 78.0, 2.6, 780.0),
    "Nagapattinam": (36.0, 80.0, 3.0, 760.0),
    "Mayiladuthurai": (36.5, 78.0, 2.8, 770.0),
    "Cuddalore":    (37.5, 74.0, 2.5, 760.0),
    "Villupuram":   (38.0, 68.0, 2.1, 810.0),
    "Kallakurichi": (38.0, 62.0, 2.0, 830.0),
    "Tiruvannamalai": (38.0, 61.0, 1.9, 820.0),
    "Perambalur":   (37.5, 62.0, 2.1, 850.0),
    "Ariyalur":     (37.0, 65.0, 2.2, 840.0),
    "Tiruchirappalli": (38.0, 62.0, 2.0, 850.0),
    "Karur":        (38.0, 58.0, 2.2, 870.0),
    "Tenkasi":      (35.0, 78.0, 3.0, 720.0),
    "Tirunelveli":  (36.0, 75.0, 3.2, 760.0),
    "Thoothukudi":  (37.0, 72.0, 3.0, 810.0),
    "Kanyakumari":  (32.0, 82.0, 3.5, 650.0),
}


# ============================================================
# THERMAL MODEL
# ============================================================

def calculate_thermal_metrics(tdb, rh, wind, solar):
    """
    Prototype integration with pythermalcomfort.

    UTCI needs:
        - dry bulb temperature
        - mean radiant temperature
        - wind speed
        - relative humidity

    Solar radiation is converted into an estimated delta-MRT
    using pythermalcomfort.solar_gain(), then added to Tdb.

    The solar geometry/view factors below are prototype assumptions.
    They should later come from location/time/solar-position data.
    """

    if not PYTHERMALCOMFORT_AVAILABLE:
        return {
            "utci": None,
            "category": "pythermalcomfort not installed",
            "risk": "DEMO",
            "tr": tdb,
        }

    # Prototype solar geometry.
    # These are intentionally isolated so they can be replaced later.
    sol_altitude = 60.0
    sharp = 0.0
    sol_transmittance = 1.0
    f_svv = 0.5
    f_bes = 0.5

    try:
        solar_result = solar_gain(
            sol_altitude=sol_altitude,
            sharp=sharp,
            sol_radiation_dir=solar,
            sol_transmittance=sol_transmittance,
            f_svv=f_svv,
            f_bes=f_bes,
            asw=0.7,
            posture="standing",
        )

        tr = tdb + float(solar_result.delta_mrt)

    except Exception:
        # Safe fallback for the prototype if solar inputs are outside
        # the solar_gain model's applicability range.
        tr = tdb

    # UTCI has a standard applicability range that requires wind > 0.5 m/s.
    model_wind = max(float(wind), 0.5)

    try:
        result = utci(
            tdb=float(tdb),
            tr=float(tr),
            v=model_wind,
            rh=float(rh),
            units="SI",
            limit_inputs=True,
            round_output=True,
        )

        utci_value = float(result.utci)
        category = str(result.stress_category)

        # UI risk bands based on UTCI heat-stress bands.
        if utci_value < 26:
            risk = "LOW"
        elif utci_value < 32:
            risk = "MODERATE"
        elif utci_value < 38:
            risk = "HIGH"
        elif utci_value < 46:
            risk = "VERY HIGH"
        else:
            risk = "EXTREME"

        return {
            "utci": utci_value,
            "category": category,
            "risk": risk,
            "tr": round(tr, 1),
        }

    except Exception:
        return {
            "utci": None,
            "category": "Outside model limits",
            "risk": "CHECK",
            "tr": round(tr, 1),
        }


def risk_color(risk):
    colors = {
        "LOW": "#B9E6D0",
        "MODERATE": "#F6E58D",
        "HIGH": "#F5B971",
        "VERY HIGH": "#F08A5D",
        "EXTREME": "#D9534F",
        "CHECK": "#D9DDE3",
        "DEMO": "#D9DDE3",
    }
    return colors.get(risk, "#D9DDE3")


# ============================================================
# MAP DATA
# ============================================================

def download_map_if_needed():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if MAP_FILE.exists():
        return

    try:
        print("Downloading Tamil Nadu map...")
        urllib.request.urlretrieve(MAP_URL, MAP_FILE)
        print(f"Saved map to: {MAP_FILE}")
    except Exception as exc:
        raise RuntimeError(
            "Could not download the Tamil Nadu GeoJSON. "
            "Check your internet connection and try again."
        ) from exc


def load_geojson():
    download_map_if_needed()

    with open(MAP_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def get_property(feature, *names):
    props = feature.get("properties", {})

    for name in names:
        value = props.get(name)
        if value not in (None, "", "null"):
            return str(value)

    return "Prototype Zone"


def geometry_rings(geometry):
    """
    Return polygon rings as a list of polygons.

    Each polygon is a list of rings:
        [outer_ring, hole_ring, ...]
    """

    if not geometry:
        return []

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])

    if geometry_type == "Polygon":
        return [coordinates]

    if geometry_type == "MultiPolygon":
        return coordinates

    return []


def create_path_from_geometry(geometry, project):
    """
    Convert GeoJSON lon/lat geometry into QPainterPath.
    """

    path = QPainterPath()

    for polygon in geometry_rings(geometry):

        for ring_index, ring in enumerate(polygon):

            if not ring:
                continue

            first_lon, first_lat = ring[0]
            first = project(first_lon, first_lat)

            path.moveTo(first)

            for lon, lat in ring[1:]:
                path.lineTo(project(lon, lat))

            path.closeSubpath()

    return path


# ============================================================
# HOVERABLE MAP ITEM
# ============================================================

class WardMapItem(QGraphicsPathItem):

    def __init__(
        self,
        path,
        zone_name,
        metrics,
        map_view,
        index,
    ):
        super().__init__(path)

        self.zone_name = zone_name
        self.metrics = metrics
        self.map_view = map_view
        self.index = index

        self.normal_brush = QBrush(
            QColor(risk_color(metrics["risk"]))
        )

        self.normal_pen = QPen(
            QColor("#7C8794"),
            1.0
        )

        self.hover_pen = QPen(
            QColor("#17202A"),
            2.2
        )

        self.setBrush(self.normal_brush)
        self.setPen(self.normal_pen)

        self.setAcceptHoverEvents(True)
        self.setZValue(1)

        # Used for the subtle 3D lift effect.
        self.setTransformOriginPoint(
            self.boundingRect().center()
        )

        self.shadow = QGraphicsPathItem(path)
        self.shadow.setBrush(
            QBrush(QColor(30, 41, 59, 45))
        )
        self.shadow.setPen(
            QPen(Qt.NoPen)
        )
        self.shadow.setZValue(0)

    def hoverEnterEvent(self, event):

        self.setBrush(
            QBrush(
                QColor(risk_color(self.metrics["risk"])).lighter(108)
            )
        )

        self.setPen(self.hover_pen)

        self.setScale(1.025)
        self.setPos(0, -4)
        self.setZValue(50)

        self.shadow.setScale(1.035)
        self.shadow.setPos(4, 5)
        self.shadow.setZValue(49)

        self.map_view.show_zone_popup(self)

        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):

        self.setBrush(self.normal_brush)
        self.setPen(self.normal_pen)

        self.setScale(1.0)
        self.setPos(0, 0)
        self.setZValue(1)

        self.shadow.setScale(1.0)
        self.shadow.setPos(0, 0)
        self.shadow.setZValue(0)

        self.map_view.hide_zone_popup()

        super().hoverLeaveEvent(event)


# ============================================================
# MAP VIEW
# ============================================================

class TamilNaduMap(QGraphicsView):

    def __init__(self):
        super().__init__()

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)

        self.setBackgroundBrush(
            QBrush(QColor("#FAFBFC"))
        )

        self.setFrameShape(QFrame.NoFrame)

        self.setMouseTracking(True)

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.setTransformationAnchor(
            QGraphicsView.AnchorUnderMouse
        )

        self.setResizeAnchor(
            QGraphicsView.AnchorViewCenter
        )

        self.popup = QFrame(self.viewport())

        self.popup.setObjectName("zonePopup")

        self.popup.setStyleSheet(
            """
            QFrame#zonePopup {
                background: #FFFFFF;
                border: 1px solid #D4DAE1;
                border-radius: 10px;
            }

            QLabel {
                color: #17202A;
            }
            """
        )

        self.popup_layout = QVBoxLayout(
            self.popup
        )

        self.popup_layout.setContentsMargins(
            12, 10, 12, 10
        )

        self.popup_layout.setSpacing(3)

        self.popup_title = QLabel()

        self.popup_title.setStyleSheet(
            "font-size: 14px; font-weight: 700;"
        )

        self.popup_value = QLabel()

        self.popup_value.setStyleSheet(
            "font-size: 12px;"
        )

        self.popup_risk = QLabel()

        self.popup_risk.setStyleSheet(
            "font-size: 12px; font-weight: 700;"
        )

        self.popup_layout.addWidget(
            self.popup_title
        )

        self.popup_layout.addWidget(
            self.popup_value
        )

        self.popup_layout.addWidget(
            self.popup_risk
        )

        self.popup.hide()

        self.zone_items = []

        self.load_map()

    def load_map(self):

        data = load_geojson()

        features = data.get("features", [])

        all_coords = []

        for feature in features:

            geometry = feature.get("geometry")

            for polygon in geometry_rings(geometry):

                for ring in polygon:

                    all_coords.extend(ring)

        if not all_coords:
            raise RuntimeError(
                "No polygon geometry was found in the Tamil Nadu map."
            )

        min_lon = min(
            point[0] for point in all_coords
        )

        max_lon = max(
            point[0] for point in all_coords
        )

        min_lat = min(
            point[1] for point in all_coords
        )

        max_lat = max(
            point[1] for point in all_coords
        )

        # Leave room around the state.
        margin = 1.5

        lon_span = max_lon - min_lon
        lat_span = max_lat - min_lat

        target_width = 1000
        target_height = 650

        scale_x = target_width / (
            lon_span + margin
        )

        scale_y = target_height / (
            lat_span + margin
        )

        scale = min(
            scale_x,
            scale_y
        )

        center_lon = (
            min_lon + max_lon
        ) / 2

        center_lat = (
            min_lat + max_lat
        ) / 2

        def project(lon, lat):

            x = (
                (lon - center_lon)
                * scale
            )

            y = (
                -(lat - center_lat)
                * scale
            )

            return QPointF(
                x,
                y
            )

        for index, feature in enumerate(features):

            geometry = feature.get(
                "geometry"
            )

            path = create_path_from_geometry(
                geometry,
                project
            )

            if path.isEmpty():
                continue

            # Most state GeoJSON datasets expose district names.
            # These are intentionally treated as prototype zones
            # until actual ward boundaries are supplied.
            zone_name = get_property(
                feature,
                "district",
                "District",
                "DISTRICT",
                "NAME_2",
                "name",
                "NAME",
            )

            weather = DEMO_WEATHER.get(
                zone_name,
                self.default_weather(index)
            )

            metrics = calculate_thermal_metrics(
                *weather
            )

            item = WardMapItem(
                path=path,
                zone_name=zone_name,
                metrics=metrics,
                map_view=self,
                index=index,
            )

            self.scene.addItem(
                item.shadow
            )

            self.scene.addItem(
                item
            )

            self.zone_items.append(item)

        self.scene.setSceneRect(
            self.scene.itemsBoundingRect().adjusted(
                -40,
                -40,
                40,
                40,
            )
        )

        self.fitInView(
            self.scene.sceneRect(),
            Qt.KeepAspectRatio
        )

    @staticmethod
    def default_weather(index):

        # Deterministic demo values for zones that do not have
        # a matching key in the demo dictionary.
        temperature = 35 + (index % 6)
        humidity = 55 + (index * 3 % 25)
        wind = 1.5 + (index % 4) * 0.4
        solar = 650 + (index % 5) * 45

        return (
            temperature,
            humidity,
            wind,
            solar,
        )

    def resizeEvent(self, event):

        super().resizeEvent(event)

        self.fitInView(
            self.scene.sceneRect(),
            Qt.KeepAspectRatio
        )

        self.popup.hide()

    def show_zone_popup(self, item):

        metrics = item.metrics

        self.popup_title.setText(
            item.zone_name
        )

        if metrics["utci"] is None:
            utci_text = "UTCI: unavailable"
        else:
            utci_text = (
                f"UTCI: {metrics['utci']:.1f} °C"
            )

        self.popup_value.setText(
            f"{utci_text}  •  "
            f"RH: {self.zone_weather(item)[1]:.0f}%"
        )

        self.popup_risk.setText(
            f"Risk: {metrics['risk']}"
        )

        self.popup_risk.setStyleSheet(
            f"""
            font-size: 12px;
            font-weight: 700;
            color: {risk_color(metrics['risk'])};
            """
        )

        self.popup.adjustSize()

        scene_pos = item.boundingRect().center()

        viewport_pos = self.mapFromScene(
            item.mapToScene(scene_pos)
        )

        x = (
            viewport_pos.x()
            - self.popup.width() // 2
        )

        y = (
            viewport_pos.y()
            - self.popup.height()
            - 14
        )

        # Keep popup inside map.
        x = max(
            8,
            min(
                x,
                self.viewport().width()
                - self.popup.width()
                - 8,
            ),
        )

        y = max(
            8,
            y,
        )

        self.popup.move(
            x,
            y
        )

        self.popup.show()
        self.popup.raise_()

    def zone_weather(self, item):

        name = item.zone_name

        return DEMO_WEATHER.get(
            name,
            self.default_weather(item.index)
        )

    def hide_zone_popup(self):

        self.popup.hide()


# ============================================================
# FORECAST PANEL
# ============================================================

class ForecastCard(QFrame):

    def __init__(
        self,
        day_name,
        date_text,
        temperature,
        humidity,
        utci_value,
        risk,
    ):

        super().__init__()

        self.setObjectName(
            "forecastCard"
        )

        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            12,
            10,
            12,
            10
        )

        layout.setSpacing(3)

        day = QLabel(
            day_name.upper()
        )

        day.setStyleSheet(
            """
            font-size: 11px;
            font-weight: 700;
            color: #667085;
            """
        )

        date_label = QLabel(
            date_text
        )

        date_label.setStyleSheet(
            "font-size: 10px; color: #98A2B3;"
        )

        temp = QLabel(
            f"{temperature:.0f}°"
        )

        temp.setStyleSheet(
            """
            font-size: 24px;
            font-weight: 700;
            color: #17202A;
            """
        )

        details = QLabel(
            f"RH {humidity:.0f}%"
        )

        details.setStyleSheet(
            "font-size: 11px; color: #667085;"
        )

        stress = QLabel(
            f"UTCI {utci_value:.1f}°C"
            if utci_value is not None
            else "UTCI —"
        )

        stress.setStyleSheet(
            "font-size: 11px; color: #475467;"
        )

        risk_label = QLabel(
            risk
        )

        risk_label.setStyleSheet(
            f"""
            font-size: 10px;
            font-weight: 700;
            color: #17202A;
            background: {risk_color(risk)};
            border-radius: 5px;
            padding: 3px 6px;
            """
        )

        layout.addWidget(day)
        layout.addWidget(date_label)
        layout.addSpacing(3)
        layout.addWidget(temp)
        layout.addWidget(details)
        layout.addWidget(stress)
        layout.addSpacing(3)
        layout.addWidget(risk_label)

        self.setStyleSheet(
            """
            QFrame#forecastCard {
                background: #FFFFFF;
                border: 1px solid #E4E7EC;
                border-radius: 10px;
            }

            QFrame#forecastCard:hover {
                border: 1px solid #98A2B3;
            }
            """
        )


class ForecastPanel(QFrame):

    def __init__(self):

        super().__init__()

        self.setObjectName(
            "forecastPanel"
        )

        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            16,
            16,
            16,
            16
        )

        layout.setSpacing(12)

        heading = QHBoxLayout()

        title = QLabel(
            "5-DAY FORECAST"
        )

        title.setStyleSheet(
            """
            font-size: 16px;
            font-weight: 700;
            color: #17202A;
            """
        )

        demo = QLabel(
            "PROTOTYPE DATA"
        )

        demo.setStyleSheet(
            """
            font-size: 9px;
            font-weight: 700;
            color: #667085;
            background: #F2F4F7;
            border-radius: 5px;
            padding: 4px 6px;
            """
        )

        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(demo)

        layout.addLayout(heading)

        subtitle = QLabel(
            "Thermal-stress outlook for the selected state"
        )

        subtitle.setStyleSheet(
            "font-size: 11px; color: #667085;"
        )

        layout.addWidget(
            subtitle
        )

        self.cards_layout = QVBoxLayout()

        self.cards_layout.setSpacing(
            8
        )

        layout.addLayout(
            self.cards_layout
        )

        layout.addStretch()

        self.populate()

        self.setStyleSheet(
            """
            QFrame#forecastPanel {
                background: #F8FAFC;
                border-left: 1px solid #E4E7EC;
            }
            """
        )

    def populate(self):

        base = [
            (38, 72, 2.1, 760),
            (39, 74, 2.0, 780),
            (40, 76, 1.8, 810),
            (39, 73, 2.2, 790),
            (37, 68, 2.6, 720),
        ]

        today = datetime.now().date()

        for index, values in enumerate(base):

            tdb, rh, wind, solar = values

            metrics = calculate_thermal_metrics(
                tdb,
                rh,
                wind,
                solar,
            )

            date = today + timedelta(
                days=index
            )

            if index == 0:
                day_name = "Today"
            elif index == 1:
                day_name = "Tomorrow"
            else:
                day_name = date.strftime("%a")

            card = ForecastCard(
                day_name=day_name,
                date_text=date.strftime("%d %b"),
                temperature=tdb,
                humidity=rh,
                utci_value=metrics["utci"],
                risk=metrics["risk"],
            )

            self.cards_layout.addWidget(
                card
            )


# ============================================================
# COLLAPSIBLE LEFT PANEL
# ============================================================

class CollapsiblePanel(QFrame):

    def __init__(
        self,
        title,
        side="left",
        parent=None,
    ):

        super().__init__(parent)

        self.setObjectName(
            "collapsiblePanel"
        )

        self._expanded = True

        self.toggle = QToolButton(
            text="☰"
        )

        self.toggle.setAutoRaise(True)

        self.toggle.setStyleSheet(
            """
            QToolButton {
                font-size: 18px;
                border: none;
            }
            """
        )

        self.toggle.clicked.connect(
            self.toggle_expanded
        )

        self.title = QLabel(
            title
        )

        self.title.setStyleSheet(
            """
            font-size: 13px;
            font-weight: 700;
            color: #17202A;
            """
        )

        self.body = QWidget()

        header = QHBoxLayout()

        header.setContentsMargins(
            0,
            0,
            0,
            0
        )

        if side == "left":

            header.addWidget(
                self.toggle
            )

            header.addWidget(
                self.title,
                1
            )

        else:

            header.addWidget(
                self.title,
                1
            )

            header.addWidget(
                self.toggle
            )

        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            10,
            10,
            10,
            10
        )

        layout.addLayout(header)

        layout.addWidget(
            self.body,
            1
        )

        self.setFixedWidth(
            210
        )

    def toggle_expanded(self):

        self._expanded = (
            not self._expanded
        )

        self.title.setVisible(
            self._expanded
        )

        self.body.setVisible(
            self._expanded
        )

        self.setFixedWidth(
            210
            if self._expanded
            else 42
        )


# ============================================================
# MAIN WINDOW
# ============================================================

class MainWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            APP_TITLE
        )

        self.resize(
            WINDOW_WIDTH,
            WINDOW_HEIGHT
        )

        self.setMinimumSize(
            1100,
            650
        )

        self.build_ui()

    def build_ui(self):

        central = QWidget()

        root = QVBoxLayout(
            central
        )

        root.setContentsMargins(
            0,
            0,
            0,
            0
        )

        root.setSpacing(0)

        # ----------------------------------------------------
        # TOP BAR
        # ----------------------------------------------------

        topbar = QFrame()

        topbar.setFixedHeight(
            64
        )

        top_layout = QHBoxLayout(
            topbar
        )

        top_layout.setContentsMargins(
            20,
            0,
            20,
            0
        )

        title = QLabel(
            APP_TITLE
        )

        title.setStyleSheet(
            """
            font-size: 18px;
            font-weight: 800;
            color: #101828;
            """
        )

        subtitle = QLabel(
            "Authority dashboard  /  Hyperlocal heat-risk prototype"
        )

        subtitle.setStyleSheet(
            """
            font-size: 11px;
            color: #667085;
            """
        )

        location = QLabel(
            "TAMIL NADU"
        )

        location.setStyleSheet(
            """
            font-size: 11px;
            font-weight: 700;
            color: #344054;
            background: #F2F4F7;
            border: 1px solid #E4E7EC;
            border-radius: 7px;
            padding: 7px 10px;
            """
        )

        top_layout.addWidget(
            title
        )

        top_layout.addSpacing(
            12
        )

        top_layout.addWidget(
            subtitle
        )

        top_layout.addStretch()

        top_layout.addWidget(
            location
        )

        topbar.setStyleSheet(
            """
            QFrame {
                background: #FFFFFF;
                border-bottom: 1px solid #E4E7EC;
            }
            """
        )

        root.addWidget(
            topbar
        )

        # ----------------------------------------------------
        # MAIN ROW
        # ----------------------------------------------------

        row = QHBoxLayout()

        row.setContentsMargins(
            0,
            0,
            0,
            0
        )

        row.setSpacing(0)

        # LEFT

        left = CollapsiblePanel(
            "CONTROLS"
        )

        left_body = QVBoxLayout(
            left.body
        )

        note = QLabel(
            "Controls will be added here."
        )

        note.setWordWrap(True)

        note.setStyleSheet(
            """
            font-size: 11px;
            color: #667085;
            padding: 6px;
            """
        )

        left_body.addWidget(
            note
        )

        prototype = QLabel(
            "PROTOTYPE\n\n"
            "Tamil Nadu map is active.\n\n"
            "Ward controls, filters and "
            "administrative drill-down "
            "can be added here later."
        )

        prototype.setWordWrap(True)

        prototype.setStyleSheet(
            """
            font-size: 11px;
            color: #475467;
            background: #F8FAFC;
            border: 1px solid #E4E7EC;
            border-radius: 8px;
            padding: 10px;
            """
        )

        left_body.addWidget(
            prototype
        )

        left_body.addStretch()

        row.addWidget(
            left
        )

        # MAP

        map_container = QFrame()

        map_container.setObjectName(
            "mapContainer"
        )

        map_layout = QVBoxLayout(
            map_container
        )

        map_layout.setContentsMargins(
            14,
            14,
            14,
            14
        )

        map_layout.setSpacing(
            8
        )

        map_header = QHBoxLayout()

        map_title = QLabel(
            "Tamil Nadu"
        )

        map_title.setStyleSheet(
            """
            font-size: 17px;
            font-weight: 750;
            color: #17202A;
            """
        )

        map_hint = QLabel(
            "Hover over a zone for details"
        )

        map_hint.setStyleSheet(
            """
            font-size: 10px;
            color: #98A2B3;
            """
        )

        map_header.addWidget(
            map_title
        )

        map_header.addStretch()

        map_header.addWidget(
            map_hint
        )

        map_layout.addLayout(
            map_header
        )

        self.map = TamilNaduMap()

        map_layout.addWidget(
            self.map,
            1
        )

        # Legend

        legend = QHBoxLayout()

        legend.addStretch()

        for label, color in [
            ("LOW", "#B9E6D0"),
            ("MODERATE", "#F6E58D"),
            ("HIGH", "#F5B971"),
            ("VERY HIGH", "#F08A5D"),
            ("EXTREME", "#D9534F"),
        ]:

            swatch = QLabel(
                f"  {label}  "
            )

            swatch.setStyleSheet(
                f"""
                QLabel {{
                    background: {color};
                    color: #17202A;
                    border-radius: 5px;
                    padding: 3px 5px;
                    font-size: 8px;
                    font-weight: 700;
                }}
                """
            )

            legend.addWidget(
                swatch
            )

        map_layout.addLayout(
            legend
        )

        map_container.setStyleSheet(
            """
            QFrame#mapContainer {
                background: #FFFFFF;
                border-right: 1px solid #E4E7EC;
            }
            """
        )

        row.addWidget(
            map_container,
            1
        )

        # RIGHT

        forecast = ForecastPanel()

        forecast.setFixedWidth(
            280
        )

        row.addWidget(
            forecast
        )

        root.addLayout(
            row,
            1
        )

        # Bottom status

        status = QLabel(
            "DEMO MODE  •  Prototype environmental data  •  "
            "Replace with ward-level weather + forecast API"
        )

        status.setAlignment(
            Qt.AlignCenter
        )

        status.setFixedHeight(
            28
        )

        status.setStyleSheet(
            """
            QLabel {
                background: #F8FAFC;
                color: #98A2B3;
                border-top: 1px solid #E4E7EC;
                font-size: 9px;
            }
            """
        )

        root.addWidget(
            status
        )

        self.setCentralWidget(
            central
        )


# ============================================================
# APPLICATION
# ============================================================

def main():

    app = QApplication(
        sys.argv
    )

    app.setStyle(
        "Fusion"
    )

    app.setStyleSheet(
        """
        QWidget {
            font-family: "Segoe UI";
        }

        QMainWindow {
            background: #FFFFFF;
        }
        """
    )

    if not PYTHERMALCOMFORT_AVAILABLE:

        print(
            "WARNING: pythermalcomfort is not installed."
        )

        print(
            "Run: python -m pip install pythermalcomfort"
        )

    try:

        window = MainWindow()

        window.show()

        sys.exit(
            app.exec_()
        )

    except Exception as exc:

        print(
            "\nAPPLICATION ERROR:\n"
        )

        print(exc)

        sys.exit(1)


if __name__ == "__main__":
    main()