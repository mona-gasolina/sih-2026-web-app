

import sys

from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

HAMBURGER = "☰"  # ☰ - three horizontal lines
COLLAPSED_WIDTH = 36
EXPANDED_WIDTH = 260


class CollapsiblePanel(QFrame):
    """A side panel that shrinks to a single hamburger button."""

    def __init__(self, title, side="left", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._expanded = True

        self.toggle = QToolButton(text=HAMBURGER)
        self.toggle.setToolTip(f"Collapse / expand {title}")
        self.toggle.setAutoRaise(True)
        self.toggle.setStyleSheet("font-size: 18px;")
        self.toggle.clicked.connect(self.toggle_expanded)

        self.title = QLabel(f"<b>{title}</b>")
        self.body = QWidget()

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        # Keep the button on the outer edge so it stays in place when collapsed.
        if side == "left":
            header.addWidget(self.toggle)
            header.addWidget(self.title, 1)
        else:
            header.addWidget(self.title, 1)
            header.addWidget(self.toggle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(header)
        layout.addWidget(self.body, 1)
        layout.addStretch(0)  # keeps the button at the top when the body is hidden

        self.setFixedWidth(EXPANDED_WIDTH)

    def toggle_expanded(self):
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded):
        self._expanded = expanded
        self.title.setVisible(expanded)
        self.body.setVisible(expanded)
        self.setFixedWidth(EXPANDED_WIDTH if expanded else COLLAPSED_WIDTH)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prototype")
        self.resize(1200, 700)

        self.left = CollapsiblePanel("Left", side="left")
        self.right = CollapsiblePanel("Right", side="right")

        self.middle = QFrame()
        self.middle.setFrameShape(QFrame.StyledPanel)
        middle_layout = QVBoxLayout(self.middle)
        middle_layout.addWidget(QLabel("<b>Middle</b>"))
        middle_layout.addStretch(1)

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(6, 6, 6, 6)
        row.addWidget(self.left)
        row.addWidget(self.middle, 1)  # middle takes all remaining width
        row.addWidget(self.right)
        self.setCentralWidget(central)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()