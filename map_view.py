from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush, QLinearGradient
from PyQt5.QtWidgets import (
    QFrame, QGraphicsPathItem, QGraphicsScene, QGraphicsView, QGridLayout, QLabel, QVBoxLayout
)

from config import (
    FS_HEADING, FS_BODY, FS_LABEL, c,
    temperature_color, risk_color, risk_gradient, qss_gradient, set_base_style,
)
from data_manager import geometry_rings, get_property, load_geojson, match_census_profile
from pipeline import placeholder_metrics


def create_path_from_geometry(geometry, project):
    path = QPainterPath()
    for polygon in geometry_rings(geometry):
        for ring in polygon:
            if not ring:
                continue
            first_lon, first_lat = ring[0]
            path.moveTo(project(first_lon, first_lat))
            for lon, lat in ring[1:]:
                path.lineTo(project(lon, lat))
            path.closeSubpath()
    return path


class ZoneItem(QGraphicsPathItem):
    def __init__(self, path, name, metrics, map_view, index):
        super().__init__(path)
        self.zone_name = name
        self.metrics = metrics
        self.map_view = map_view
        self.index = index
        self.selected = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(1)
        self.setTransformOriginPoint(path.boundingRect().center())

        self.shadow = QGraphicsPathItem(path)
        self.shadow.setBrush(QBrush(QColor(15, 23, 42, 40)))
        self.shadow.setPen(QPen(Qt.NoPen))
        self.shadow.setZValue(0)
        self.shadow.setTransformOriginPoint(path.boundingRect().center())
        self.restyle()

    def restyle(self):
        self.setBrush(self.map_view.zone_brush(self.metrics, self.path().boundingRect()))
        if self.selected:
            self.setPen(QPen(QColor(c("text")), 3.2))
            self.setZValue(40)
        else:
            self.setPen(QPen(QColor(c("mapEdge")), 1.2))
            self.setZValue(1)

    def set_metrics(self, metrics):
        self.metrics = metrics
        self.restyle()

    def set_selected(self, selected):
        self.selected = selected
        self.restyle()

    def hoverEnterEvent(self, event):
        self.setPen(QPen(QColor(c("text")), 2.8))
        self.setScale(1.02)
        self.setPos(0, -2)
        self.setZValue(50)
        self.shadow.setScale(1.025)
        self.shadow.setPos(3, 4)
        self.shadow.setZValue(49)
        self.map_view.show_zone_popup(self, event.scenePos())
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event):
        self.map_view.show_zone_popup(self, event.scenePos())
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.setScale(1.0)
        self.setPos(0, 0)
        self.shadow.setScale(1.0)
        self.shadow.setPos(0, 0)
        self.shadow.setZValue(0)
        self.restyle()
        self.map_view.hide_zone_popup()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.map_view.select_zone(self)
        super().mousePressEvent(event)


class TamilNaduMap(QGraphicsView):
    def __init__(self, demographic_profiles, on_select):
        super().__init__()
        self.demographic_profiles = demographic_profiles
        self.on_select = on_select
        self.zone_items = []
        self.popup = None
        self.color_mode = "temperature"

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setMinimumSize(300, 220)
        self.setAccessibleName("Heat risk map of Tamil Nadu districts")

        self._create_popup()
        self.load_map()
        self.on_theme_changed()

    # ------------------------------------------------------------------ theme
    def on_theme_changed(self):
        self.setBackgroundBrush(QBrush(QColor(c("mapBg"))))
        for item in self.zone_items:
            item.restyle()

    def set_color_mode(self, mode):
        self.color_mode = mode
        for item in self.zone_items:
            item.restyle()

    def zone_brush(self, metrics, rect):
        if not metrics.get("loaded"):
            return QBrush(QColor(c("surface2")))
        if self.color_mode == "temperature":
            v = float(metrics.get("temperature", 0) or 0)
            top, mid, bottom = temperature_color(v - 1.5), temperature_color(v), temperature_color(v + 1.5)
        else:
            v = float(metrics.get("risk_score", 0) or 0)
            top, mid, bottom = risk_color(v - 5), risk_color(v), risk_color(v + 5)
        gradient = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom() or rect.top() + 1)
        gradient.setColorAt(0.0, QColor(top).lighter(108))
        gradient.setColorAt(0.5, QColor(mid))
        gradient.setColorAt(1.0, QColor(bottom))
        return QBrush(gradient)

    # ------------------------------------------------------------------ hover card
    def _create_popup(self):
        self.popup = QFrame(self.viewport())
        self.popup.setObjectName("zonePopup")
        set_base_style(self.popup, """
            QFrame#zonePopup { background:$surface; border:1px solid $border; border-radius:14px; }
            QLabel { color:$text; background:transparent; border:none; }
        """)
        layout = QVBoxLayout(self.popup)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.popup_title = QLabel()
        set_base_style(self.popup_title, f"font-size:{FS_HEADING}px;font-weight:800;")
        layout.addWidget(self.popup_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(6)
        self.popup_values = {}
        rows = ("Temperature now", "Feels like today (max)", "Humidity", "Risk score", "Population (2011)")
        for row, key in enumerate(rows):
            name = QLabel(key)
            set_base_style(name, f"font-size:{FS_BODY}px;color:$muted;")
            value = QLabel()
            set_base_style(value, f"font-size:{FS_BODY}px;font-weight:700;")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(name, row, 0)
            grid.addWidget(value, row, 1)
            self.popup_values[key] = value
        layout.addLayout(grid)

        self.popup_risk = QLabel()
        layout.addWidget(self.popup_risk)
        hint = QLabel("Click for details")
        set_base_style(hint, "font-size:13px;color:$subtle;")
        layout.addWidget(hint)
        self.popup.hide()

    def show_zone_popup(self, item, scene_pos):
        m = item.metrics
        pop = m.get("demographic", {}).get("population", 0)
        self.popup_title.setText(item.zone_name)
        if m.get("loaded"):
            self.popup_values["Temperature now"].setText(f"{m['temperature']:.1f} °C")
            self.popup_values["Feels like today (max)"].setText(f"{m['today_peak_stress']:.0f} °C")
            self.popup_values["Humidity"].setText(f"{m['humidity']:.0f}%")
            self.popup_values["Risk score"].setText(f"{m['risk_score']:.0f} / 100")
        else:
            for key in ("Temperature now", "Feels like today (max)", "Humidity", "Risk score"):
                self.popup_values[key].setText("…")
        self.popup_values["Population (2011)"].setText(f"{pop:,}" if pop else "—")

        start, end, text_color = risk_gradient(m.get("risk_score", 0))
        imd = m.get("imd", {}).get("code", "GREEN")
        self.popup_risk.setText(f"{m.get('risk', '…').title()} heat stress"
                                + (f"  ·  {imd.title()} alert" if m.get("loaded") and imd != "GREEN" else ""))
        set_base_style(
            self.popup_risk,
            f"font-size:{FS_LABEL}px;font-weight:800;color:{text_color};"
            f"background:{qss_gradient(start, end)};border-radius:8px;padding:8px 10px;",
        )
        self.popup.adjustSize()

        viewport_pos = self.mapFromScene(scene_pos)
        x = viewport_pos.x() + 18
        y = viewport_pos.y() - self.popup.height() - 18
        if x + self.popup.width() > self.viewport().width() - 8:
            x = viewport_pos.x() - self.popup.width() - 18
        if y < 8:
            y = viewport_pos.y() + 18
        x = max(8, min(x, self.viewport().width() - self.popup.width() - 8))
        y = max(8, min(y, self.viewport().height() - self.popup.height() - 8))
        self.popup.move(x, y)
        self.popup.show()
        self.popup.raise_()

    def hide_zone_popup(self):
        self.popup.hide()

    # ------------------------------------------------------------------ geometry
    def load_map(self):
        data = load_geojson()
        features = data.get("features", [])
        all_coords = []
        for feature in features:
            for polygon in geometry_rings(feature.get("geometry")):
                for ring in polygon:
                    all_coords.extend(ring)
        if not all_coords:
            raise RuntimeError("No polygon geometry was found in the Tamil Nadu map.")

        min_lon = min(p[0] for p in all_coords)
        max_lon = max(p[0] for p in all_coords)
        min_lat = min(p[1] for p in all_coords)
        max_lat = max(p[1] for p in all_coords)
        scale = min(1250 / max(max_lon - min_lon, 0.1), 760 / max(max_lat - min_lat, 0.1)) * 0.88
        center_lon, center_lat = (min_lon + max_lon) / 2, (min_lat + max_lat) / 2

        def project(lon, lat):
            return QPointF((lon - center_lon) * scale, -(lat - center_lat) * scale)

        for index, feature in enumerate(features):
            path = create_path_from_geometry(feature.get("geometry"), project)
            if path.isEmpty():
                continue
            name = get_property(feature, "district", "District", "DISTRICT", "NAME_2", "name", "NAME")
            demographic = match_census_profile(name, self.demographic_profiles)
            item = ZoneItem(path, name, placeholder_metrics(demographic), self, index)
            self.scene.addItem(item.shadow)
            self.scene.addItem(item)
            self.zone_items.append(item)

        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40))
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    # ------------------------------------------------------------------ selection
    def select_zone(self, item):
        self.hide_zone_popup()
        self.on_select(item)

    def highlight(self, item):
        for zone in self.zone_items:
            zone.set_selected(zone is item)

    def find(self, name):
        for item in self.zone_items:
            if item.zone_name.lower() == name.lower():
                return item
        return None

    def select_by_name(self, name):
        item = self.find(name)
        if item:
            self.select_zone(item)
        return item

    def update_zone(self, name, metrics):
        item = self.find(name)
        if item:
            item.set_metrics(metrics)
        return item

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.scene.sceneRect().isValid():
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.popup.hide()
