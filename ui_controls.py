"""Small shared controls: text-size stepper, light/dark toggle, eye icons."""
from PyQt5.QtCore import Qt, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QAction, QPushButton

from config import (
    FONT_SCALE_MIN, FONT_SCALE_MAX, FONT_SCALE_STEP,
    set_base_style, apply_font_scale, font_scale, clamp_scale, save_font_scale,
    set_theme, save_theme, theme_name, c,
)

CONTROL_STYLE = """
    QFrame#ctrlBox { background:$surface2; border:1px solid $border; border-radius:12px; }
    QLabel { background:transparent; border:none; color:$text; font-size:14px; font-weight:700; }
    QPushButton {
        background:$surface; color:$text; border:1.5px solid $border;
        border-radius:9px; padding:6px 12px; font-weight:800; font-size:15px; min-width:34px;
    }
    QPushButton:hover { background:$chip; border-color:$borderStrong; }
    QPushButton:disabled { color:$subtle; background:$surface2; }
    QPushButton:focus { border:2px solid $focus; }
"""


class TextSizeControl(QFrame):
    """A− [100%] A+ — scales every font in the app and remembers the choice."""
    changed = pyqtSignal(float)

    def __init__(self, show_caption=True, parent=None):
        super().__init__(parent)
        self.setObjectName("ctrlBox")
        set_base_style(self, CONTROL_STYLE)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(6)
        if show_caption:
            layout.addWidget(QLabel("Text size"))
        self.down = QPushButton("A−")
        self.reset = QPushButton("100%")
        self.up = QPushButton("A+")
        self.down.setToolTip("Smaller text  (Ctrl + −)")
        self.up.setToolTip("Larger text  (Ctrl + +)")
        self.reset.setToolTip("Reset text size  (Ctrl + 0)")
        self.down.setAccessibleName("Decrease text size")
        self.up.setAccessibleName("Increase text size")
        for b in (self.down, self.reset, self.up):
            b.setCursor(Qt.PointingHandCursor)
            layout.addWidget(b)
        self.down.clicked.connect(lambda: self.set_scale(font_scale() - FONT_SCALE_STEP))
        self.up.clicked.connect(lambda: self.set_scale(font_scale() + FONT_SCALE_STEP))
        self.reset.clicked.connect(lambda: self.set_scale(1.0))
        self.sync()

    def set_scale(self, scale):
        scale = clamp_scale(scale)
        apply_font_scale(None, scale)          # whole application
        save_font_scale(scale)
        self.changed.emit(scale)

    def sync(self):
        s = font_scale()
        self.reset.setText(f"{int(round(s * 100))}%")
        self.down.setEnabled(s > FONT_SCALE_MIN)
        self.up.setEnabled(s < FONT_SCALE_MAX)

    def on_theme_changed(self):   # called by config.restyle
        self.sync()


class ThemeToggle(QPushButton):
    """Switches light ↔ dark and remembers the choice."""
    changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        set_base_style(self, """
            QPushButton {
                background:$surface2; color:$text; border:1px solid $border;
                border-radius:12px; padding:9px 14px; font-weight:700; font-size:14px;
            }
            QPushButton:hover { background:$chip; border-color:$borderStrong; }
            QPushButton:focus { border:2px solid $focus; }
        """)
        self.clicked.connect(self.toggle)
        self.sync()

    def toggle(self):
        new = "dark" if theme_name() == "light" else "light"
        set_theme(new)
        save_theme(new)
        self.changed.emit(new)

    def sync(self):
        dark = theme_name() == "dark"
        self.setText("☀  Light mode" if dark else "☾  Dark mode")
        self.setToolTip("Switch to light mode" if dark else "Switch to dark mode")

    def on_theme_changed(self):
        self.sync()


# ---------------------------------------------------------------------------
# Password field with eye toggle
# ---------------------------------------------------------------------------
def eye_icon(crossed, color, size=48):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), size * 0.08, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    s = float(size)
    outline = QPainterPath()
    outline.moveTo(s * 0.08, s * 0.5)
    outline.quadTo(s * 0.5, s * 0.10, s * 0.92, s * 0.5)
    outline.quadTo(s * 0.5, s * 0.90, s * 0.08, s * 0.5)
    p.drawPath(outline)
    p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.13, s * 0.13)
    if crossed:
        p.drawLine(QPointF(s * 0.16, s * 0.84), QPointF(s * 0.84, s * 0.16))
    p.end()
    return QIcon(pixmap)


class PasswordField(QLineEdit):
    """
    Password input with an eye button.
    Crossed eye = hidden (dots, default). Open eye = password visible.
    """

    def __init__(self, placeholder="Password", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setEchoMode(QLineEdit.Password)
        self._toggle = QAction(self)
        self._toggle.triggered.connect(self.toggle_visibility)
        self.addAction(self._toggle, QLineEdit.TrailingPosition)
        self._refresh_icon()

    def _refresh_icon(self):
        visible = self.echoMode() == QLineEdit.Normal
        self._toggle.setIcon(eye_icon(crossed=not visible, color=c("text") if visible else c("muted")))
        tip = "Hide password" if visible else "Show password"
        self._toggle.setText(tip)
        self._toggle.setToolTip(tip)

    def toggle_visibility(self):
        self.setEchoMode(QLineEdit.Password if self.echoMode() == QLineEdit.Normal else QLineEdit.Normal)
        self._refresh_icon()
        self.setFocus()
        self.setCursorPosition(len(self.text()))

    def on_theme_changed(self):
        self._refresh_icon()


def caps_lock_on():
    """Windows only; returns False elsewhere."""
    try:
        import ctypes
        return bool(ctypes.WinDLL("User32.dll").GetKeyState(0x14) & 1)
    except Exception:
        return False
