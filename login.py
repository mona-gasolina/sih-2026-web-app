from PyQt5.QtCore import Qt, QEvent, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget
)

from auth import MIN_PASSWORD_LENGTH, password_problems, password_strength
from config import (
    APP_TITLE, APP_VERSION, TEMP_GRADIENT_STOPS, FS_SMALL, FS_LABEL, FS_BODY, FS_HEADING,
    FS_BRAND, FS_TITLE, set_base_style,
)
from ui_controls import PasswordField, TextSizeControl, ThemeToggle, caps_lock_on, fit_to_screen

# ---------------------------------------------------------------------------
# Shared form styling ($tokens are filled from the active light/dark theme)
# ---------------------------------------------------------------------------
FORM_STYLE = f"""
    QDialog {{ background: $bg; }}
    QFrame#card {{ background: $surface; border: 1px solid $border; border-radius: 18px; }}
    QLabel {{ color: $text; font-size:{FS_BODY}px; background: transparent; }}
    QLabel#heading {{ color: $text; font-size:{FS_TITLE}px; font-weight: 800; }}
    QLabel#section {{ color: $muted; font-size:{FS_LABEL}px; font-weight: 800; }}
    QLabel#subtitle {{ color: $muted; font-size:{FS_BODY}px; }}
    QLabel#label {{ color: $text; font-size:{FS_LABEL}px; font-weight: 700; }}
    QLabel#hint {{ color: $subtle; font-size:{FS_SMALL}px; }}
    QLabel#error {{
        color: $danger; background: $dangerBg; border: 1px solid $dangerBorder;
        border-radius: 9px; padding: 10px 12px; font-size:{FS_BODY}px;
    }}
    QLabel#warn {{
        color: $warnText; background: $warnBg; border-radius: 8px;
        padding: 6px 10px; font-size:{FS_SMALL}px; font-weight: 700;
    }}
    QLabel#info {{
        color: $muted; background: $surface2; border: 1px solid $border;
        border-radius: 9px; padding: 10px 12px; font-size:{FS_SMALL}px;
    }}
    QLineEdit, QComboBox {{
        background: $input; border: 1.5px solid $border; border-radius: 10px;
        padding: 10px 12px; min-height: 26px; color: $text; font-size:{FS_BODY}px;
        selection-background-color: $primary;
    }}
    QLineEdit:hover, QComboBox:hover {{ border-color: $borderStrong; }}
    QLineEdit:focus, QComboBox:focus {{ border: 2px solid $focus; }}
    QLineEdit:disabled, QComboBox:disabled {{ background: $surface2; color: $subtle; }}
    QPushButton#primary {{
        background: $primary; color: $onPrimary; border: none; border-radius: 11px;
        padding: 13px 20px; font-weight: 700; font-size:{FS_BODY}px;
    }}
    QPushButton#primary:hover {{ background: $primaryHover; }}
    QPushButton#primary:disabled {{ background: $borderStrong; color: $surface; }}
    QPushButton#secondary {{
        background: $surface; color: $text; border: 1.5px solid $border;
        border-radius: 11px; padding: 12px 18px; font-weight: 700; font-size:{FS_BODY}px;
    }}
    QPushButton#secondary:hover {{ background: $chip; }}
    QPushButton#secondary:disabled {{ color: $subtle; }}
    QPushButton#link {{
        background: transparent; color: $focus; border: none; padding: 4px 0;
        font-size:{FS_SMALL}px; font-weight: 700; text-align: left;
    }}
    QPushButton#link:hover {{ text-decoration: underline; }}
    QPushButton:focus {{ outline: none; border: 2px solid $focus; }}
    QProgressBar {{ background: $surface2; border: none; border-radius: 3px; max-height: 6px; }}
    QTableWidget {{
        background: $surface; alternate-background-color: $surface2; color: $text;
        border: 1px solid $border; border-radius: 10px; gridline-color: $border;
        font-size:{FS_BODY}px; selection-background-color: $primary; selection-color: $onPrimary;
    }}
    QHeaderView::section {{
        background: $surface2; color: $muted; border: none; border-bottom: 1px solid $border;
        padding: 10px 8px; font-size:{FS_LABEL}px; font-weight: 800;
    }}
"""


def _label(text, name="label"):
    label = QLabel(text)
    label.setObjectName(name)
    return label


def _scroll_shell(dialog, margins):
    """Scrollable body + fixed footer, so a dialog still works on a small screen."""
    shell = QVBoxLayout(dialog)
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    inner = QWidget()
    inner.setObjectName("dialogBody")
    set_base_style(inner, "QWidget#dialogBody { background:$bg; }")
    body = QVBoxLayout(inner)
    body.setContentsMargins(*margins)
    scroll.setWidget(inner)
    shell.addWidget(scroll, 1)
    footer = QHBoxLayout()
    footer.setContentsMargins(margins[0], 10, margins[2], margins[3])
    shell.addLayout(footer)
    return body, footer


def _field(caption, widget, hint=None):
    box = QVBoxLayout()
    box.setSpacing(6)
    box.addWidget(_label(caption))
    box.addWidget(widget)
    if hint is not None:
        box.addWidget(hint)
    return box


# ---------------------------------------------------------------------------
# Brand panel (left side of the sign-in screen)
# ---------------------------------------------------------------------------
class BrandPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("brandPanel")
        stops = ", ".join(
            f"stop:{(t - 15) / 30:.2f} {c}" for t, c in TEMP_GRADIENT_STOPS
        )
        set_base_style(self, f"""
            QFrame#brandPanel {{
                background: qlineargradient(x1:0, y1:0, x2:0.35, y2:1,
                    stop:0 #0B1735, stop:0.6 #16295C, stop:1 #3A1C4F);
                border-radius: 18px;
            }}
            QLabel {{ color: #FFFFFF; background: transparent; }}
            QFrame#heatStrip {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, {stops});
                border-radius: 4px; min-height: 8px; max-height: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 36)
        layout.setSpacing(14)

        badge = QLabel("SIH 2026  •  PS 26083")
        set_base_style(badge, f"font-size:{FS_SMALL}px;font-weight:800;color:#C7D2FE;"
                              "background:rgba(255,255,255,0.10);border-radius:8px;padding:6px 10px;")
        layout.addWidget(badge, 0, Qt.AlignLeft)
        layout.addSpacing(16)

        title = QLabel(APP_TITLE)
        set_base_style(title, f"font-size:{FS_BRAND + 10}px;font-weight:800;color:#FFFFFF;")
        layout.addWidget(title)
        strip = QFrame()
        strip.setObjectName("heatStrip")
        layout.addWidget(strip)

        tagline = QLabel("Extreme heatwave early warning & human thermal stress index for city authorities.")
        tagline.setWordWrap(True)
        set_base_style(tagline, f"font-size:{FS_HEADING}px;color:#E0E7FF;")
        layout.addWidget(tagline)
        layout.addSpacing(18)

        for heading, text in (
            ("Human thermal stress", "Temperature, humidity, wind and sun combined into one index."),
            ("District risk maps", "Colour-coded districts with 5-day outlooks and drill-down; ward-ready."),
            ("Confirmed alerts", "IMD heat-wave criteria, sent only when forecast updates agree."),
        ):
            row = QVBoxLayout()
            row.setSpacing(2)
            h = QLabel("●  " + heading)
            set_base_style(h, f"font-size:{FS_BODY}px;font-weight:800;color:#FFFFFF;")
            t = QLabel(text)
            t.setWordWrap(True)
            set_base_style(t, f"font-size:{FS_SMALL}px;color:#C7D2FE;padding-left:22px;")
            row.addWidget(h)
            row.addWidget(t)
            layout.addLayout(row)

        layout.addStretch(1)
        foot = QLabel(f"Team Kelvin  •  {APP_VERSION}")
        set_base_style(foot, f"font-size:{FS_SMALL}px;color:#A5B4FC;")
        layout.addWidget(foot)


# ---------------------------------------------------------------------------
# Sign in
# ---------------------------------------------------------------------------
class LoginDialog(QDialog):
    ROLE_MAP = {
        "City Administrator": "city_admin",
        "System Admin": "admin",
        "Public User (coming soon)": "public",
    }

    def __init__(self, auth_manager, parent=None):
        super().__init__(parent)
        self.auth = auth_manager
        self.user = None
        self.setWindowTitle("Heat Intelligence – Sign in")
        self.setMinimumSize(420, 420)
        fit_to_screen(self, 1120, 760)
        set_base_style(self, FORM_STYLE)

        # Scrolls instead of clipping when a large text size is chosen.
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("loginInner")
        set_base_style(inner, "QWidget#loginInner { background:$bg; }")
        scroll.setWidget(inner)
        shell.addWidget(scroll)

        outer = QHBoxLayout(inner)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(24)
        self.brand = BrandPanel()
        outer.addWidget(self.brand, 5)

        right = QVBoxLayout()
        right.setSpacing(16)
        controls = QHBoxLayout()
        controls.addStretch()
        controls.addWidget(ThemeToggle())
        controls.addWidget(TextSizeControl())
        right.addLayout(controls)

        card = QFrame()
        card.setObjectName("card")
        form = QVBoxLayout(card)
        form.setContentsMargins(40, 36, 40, 36)
        form.setSpacing(16)

        form.addWidget(_label("Sign in", "heading"))
        sub = _label("Authorised city administration staff only.", "subtitle")
        form.addWidget(sub)
        form.addSpacing(4)

        self.role = QComboBox()
        self.role.addItems(list(self.ROLE_MAP.keys()))
        self.role.setCursor(Qt.PointingHandCursor)
        self.role.currentTextChanged.connect(self._role_changed)
        form.addLayout(_field("Access type", self.role))

        self.username = QLineEdit()
        self.username.setPlaceholderText("Your assigned login ID")
        self.username.textChanged.connect(self._clear_error)
        form.addLayout(_field("Login ID", self.username))

        self.password = PasswordField("Enter your password")
        self.password.textChanged.connect(self._clear_error)
        self.password.installEventFilter(self)
        self.caps = _label("Caps Lock is on", "warn")
        self.caps.hide()
        pw_box = _field("Password", self.password)
        pw_box.addWidget(self.caps, 0, Qt.AlignLeft)
        form.addLayout(pw_box)

        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self.try_login)

        self.error = _label("", "error")
        self.error.setWordWrap(True)
        self.error.hide()
        form.addWidget(self.error)

        self.login_btn = QPushButton("Sign in")
        self.login_btn.setObjectName("primary")
        self.login_btn.setDefault(True)
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.clicked.connect(self.try_login)
        form.addWidget(self.login_btn)

        forgot = QPushButton("Forgot your password?")
        forgot.setObjectName("link")
        forgot.setCursor(Qt.PointingHandCursor)
        forgot.clicked.connect(lambda: QMessageBox.information(
            self, "Password help",
            "For security, passwords are reset by your System Admin.\n\n"
            "Ask them to open Manage Access → select your account → Reset password.",
        ))
        form.addWidget(forgot, 0, Qt.AlignLeft)

        demo = _label("Demo login:  System Admin  ·  admin  ·  Admin@123", "info")
        demo.setWordWrap(True)
        form.addWidget(demo)

        right.addWidget(card)
        right.addStretch(1)
        notice = _label("Authorised use only. Sign-in activity is recorded on this device.", "hint")
        notice.setAlignment(Qt.AlignCenter)
        right.addWidget(notice)
        outer.addLayout(right, 4)

        self._caps_timer = QTimer(self)
        self._caps_timer.timeout.connect(self._update_caps)
        self._caps_timer.start(400)
        self.username.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.brand.setVisible(self.width() >= 860)      # small screens: sign-in form only

    def eventFilter(self, obj, event):
        if obj is self.password and event.type() in (QEvent.FocusIn, QEvent.FocusOut, QEvent.KeyRelease):
            self._update_caps()
        return super().eventFilter(obj, event)

    def _update_caps(self):
        self.caps.setVisible(self.password.hasFocus() and caps_lock_on())

    def _role_changed(self, text):
        public = self.ROLE_MAP[text] == "public"
        self.username.setEnabled(not public)
        self.password.setEnabled(not public)
        self.login_btn.setText("Public access is coming soon" if public else "Sign in")
        self.login_btn.setEnabled(not public)
        self._clear_error()

    def _clear_error(self, *_):
        self.error.hide()

    def _show_error(self, message):
        self.error.setText(message)
        self.error.show()

    def try_login(self):
        role = self.ROLE_MAP[self.role.currentText()]
        if role == "public":
            return
        username = self.username.text().strip()
        if not username or not self.password.text():
            self._show_error("Please enter both your login ID and password.")
            return
        user, message = self.auth.authenticate(username, self.password.text(), role)
        if not user:
            self._show_error(message)
            self.password.selectAll()
            self.password.setFocus()
            return
        self._caps_timer.stop()
        self.user = user
        self.accept()


# ---------------------------------------------------------------------------
# Create a city administrator account
# ---------------------------------------------------------------------------
class StrengthMeter(QWidget):
    LABELS = ["", "Weak", "Fair", "Good", "Strong"]
    COLOURS = ["#94A3B8", "#DC2626", "#F97316", "#EAB308", "#16A34A"]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.bar = QProgressBar()
        self.bar.setRange(0, 4)
        self.bar.setTextVisible(False)
        self.text = _label("", "hint")
        layout.addWidget(self.bar, 1)
        layout.addWidget(self.text)
        self.update_for("")

    def update_for(self, password):
        score = password_strength(password)
        self.bar.setValue(score)
        colour = self.COLOURS[score]
        set_base_style(self.bar, f"QProgressBar {{ background:$surface2; border:none; border-radius:3px;"
                                 f" max-height:6px; }} QProgressBar::chunk {{ background:{colour}; border-radius:3px; }}")
        missing = password_problems(password)
        if not password:
            self.text.setText(f"Min. {MIN_PASSWORD_LENGTH} chars, upper & lower case, a number")
        elif missing:
            self.text.setText("Needs " + ", ".join(missing))
        else:
            self.text.setText(self.LABELS[score])


class AdminUserDialog(QDialog):
    def __init__(self, auth_manager, parent=None, districts=None):
        super().__init__(parent)
        self.auth = auth_manager
        self.setWindowTitle("New City Administrator Account")
        self.setMinimumSize(480, 400)
        fit_to_screen(self, 860, 780)
        set_base_style(self, FORM_STYLE)

        outer, buttons = _scroll_shell(self, (32, 28, 32, 20))
        outer.setSpacing(10)
        outer.addWidget(_label("New city administrator", "heading"))
        note = _label("Creates an assigned login for an authorised officer. Heat alerts for the "
                      "assigned district are sent to the mobile number given here.", "subtitle")
        note.setWordWrap(True)
        outer.addWidget(note)
        outer.addSpacing(10)

        self.full_name = QLineEdit(placeholderText="e.g. R. Priya")
        self.designation = QLineEdit(placeholderText="e.g. Deputy Commissioner (Health)")
        self.city = QLineEdit(placeholderText="e.g. Greater Chennai Corporation")
        self.district = QComboBox()
        self.district.addItem("— Select district —")
        self.district.addItems(sorted(districts or []))
        self.mobile = QLineEdit(placeholderText="10-digit mobile, e.g. 98765 43210")
        self.username = QLineEdit(placeholderText="e.g. chennai.health")
        self.password = PasswordField("Create a password")
        self.confirm = PasswordField("Type the password again")
        self.meter = StrengthMeter()
        self.password.textChanged.connect(self.meter.update_for)

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(14)
        grid.addWidget(_label("OFFICER DETAILS", "section"), 0, 0, 1, 2)
        grid.addLayout(_field("Full name", self.full_name), 1, 0)
        grid.addLayout(_field("Designation", self.designation), 1, 1)
        grid.addLayout(_field("City / authority *", self.city), 2, 0)
        grid.addLayout(_field("Assigned district (for alerts)", self.district), 2, 1)
        grid.addLayout(_field("Mobile for SMS / WhatsApp alerts", self.mobile,
                              _label("Optional. +91 is added automatically.", "hint")), 3, 0)
        grid.addWidget(_label("SIGN-IN", "section"), 4, 0, 1, 2)
        grid.addLayout(_field("Login ID *", self.username,
                              _label("3–32 letters, numbers, dot, dash or underscore.", "hint")), 5, 0)
        grid.addLayout(_field("Password *", self.password, self.meter), 6, 0)
        grid.addLayout(_field("Confirm password *", self.confirm), 6, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        for w in (self.full_name, self.designation, self.city, self.mobile, self.username,
                  self.password, self.confirm):
            w.textChanged.connect(lambda *_: self.error.hide())

        self.error = _label("", "error")
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addSpacing(6)
        outer.addWidget(self.error)
        outer.addStretch(1)

        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondary")
        create = QPushButton("Create account")
        create.setObjectName("primary")
        create.setDefault(True)
        cancel.clicked.connect(self.reject)
        create.clicked.connect(self.create)
        buttons.addWidget(cancel)
        buttons.addWidget(create)

    def _fail(self, message):
        self.error.setText(message)
        self.error.show()

    def create(self):
        if self.password.text() != self.confirm.text():
            self._fail("The two passwords do not match.")
            return
        district = self.district.currentText() if self.district.currentIndex() > 0 else ""
        try:
            self.auth.create_city_admin(
                self.username.text(), self.password.text(), self.city.text(),
                full_name=self.full_name.text(), designation=self.designation.text(),
                district=district, mobile=self.mobile.text(),
            )
        except ValueError as exc:
            self._fail(str(exc))
            return
        self.accept()


class ResetPasswordDialog(QDialog):
    def __init__(self, auth_manager, username, parent=None):
        super().__init__(parent)
        self.auth, self.username = auth_manager, username
        self.setWindowTitle("Reset password")
        self.setMinimumWidth(520)
        set_base_style(self, FORM_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        layout.addWidget(_label(f"Reset password for “{username}”", "heading"))
        self.password = PasswordField("New password")
        self.confirm = PasswordField("Type it again")
        self.meter = StrengthMeter()
        self.password.textChanged.connect(self.meter.update_for)
        layout.addLayout(_field("New password", self.password, self.meter))
        layout.addLayout(_field("Confirm password", self.confirm))
        self.error = _label("", "error")
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondary")
        ok = QPushButton("Reset password")
        ok.setObjectName("primary")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.submit)
        row.addWidget(cancel)
        row.addWidget(ok)
        layout.addLayout(row)

    def submit(self):
        if self.password.text() != self.confirm.text():
            self.error.setText("The two passwords do not match.")
            self.error.show()
            return
        try:
            self.auth.reset_password(self.username, self.password.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.accept()


# ---------------------------------------------------------------------------
# Manage access (System Admin)
# ---------------------------------------------------------------------------
class AccessManagerDialog(QDialog):
    COLUMNS = ["Name", "Login ID", "Role", "District", "Mobile", "Status", "Last sign-in"]

    def __init__(self, auth_manager, parent=None, districts=None):
        super().__init__(parent)
        self.auth = auth_manager
        self.districts = districts or []
        self.setWindowTitle("Manage Access")
        self.setMinimumSize(600, 400)
        fit_to_screen(self, 1120, 660)
        set_base_style(self, FORM_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(_label("Manage access", "heading"))
        titles.addWidget(_label("City administrator accounts and who receives heat alerts.", "subtitle"))
        header.addLayout(titles)
        header.addStretch()
        new_btn = QPushButton("+  New account")
        new_btn.setObjectName("primary")
        new_btn.clicked.connect(self.create_account)
        header.addWidget(new_btn, 0, Qt.AlignVCenter)
        layout.addLayout(header)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)     # name takes the spare width
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.toggle_btn = QPushButton("Deactivate")
        self.toggle_btn.setObjectName("secondary")
        self.toggle_btn.clicked.connect(self.toggle_active)
        self.reset_btn = QPushButton("Reset password")
        self.reset_btn.setObjectName("secondary")
        self.reset_btn.clicked.connect(self.reset_password)
        close = QPushButton("Close")
        close.setObjectName("secondary")
        close.clicked.connect(self.accept)
        actions.addWidget(self.toggle_btn)
        actions.addWidget(self.reset_btn)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        self.users = self.auth.list_users()
        self.table.setRowCount(len(self.users))
        for row, u in enumerate(self.users):
            mobile = u.get("mobile", "")
            values = [
                u.get("full_name") or "—",
                u["username"],
                "System Admin" if u["role"] == "admin" else "City Administrator",
                u.get("district") or "—",
                ("••••" + mobile[-4:]) if mobile else "—",
                "Active" if u.get("active", True) else "Deactivated",
                (u.get("last_login") or "Never").replace("T", "  "),
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self._sync_buttons()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.users[rows[0].row()] if rows else None

    def _sync_buttons(self):
        user = self._selected()
        editable = user is not None and user["role"] != "admin"
        self.toggle_btn.setEnabled(editable)
        self.reset_btn.setEnabled(user is not None)
        if user is not None:
            self.toggle_btn.setText("Deactivate" if user.get("active", True) else "Reactivate")

    def create_account(self):
        if AdminUserDialog(self.auth, self, self.districts).exec_():
            self.refresh()

    def toggle_active(self):
        user = self._selected()
        if not user:
            return
        activate = not user.get("active", True)
        verb = "Reactivate" if activate else "Deactivate"
        if QMessageBox.question(self, f"{verb} account",
                                f"{verb} the account “{user['username']}”?") != QMessageBox.Yes:
            return
        try:
            self.auth.set_active(user["username"], activate)
        except ValueError as exc:
            QMessageBox.warning(self, "Not allowed", str(exc))
        self.refresh()

    def reset_password(self):
        user = self._selected()
        if user and ResetPasswordDialog(self.auth, user["username"], self).exec_():
            QMessageBox.information(self, "Password reset", "The password has been reset.")
