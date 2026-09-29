import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime

from functools import wraps

from config import USERS_FILE, DATA_DIR, atomic_write_text, file_lock

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
MIN_PASSWORD_LENGTH = 8
MOBILE_PATTERN = re.compile(r"^\+?[0-9]{10,15}$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


def _hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000,
    ).hex()
    return salt, digest


def password_problems(password):
    """Human-readable list of unmet password rules (empty = OK)."""
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"at least {MIN_PASSWORD_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        problems.append("an uppercase letter")
    if not re.search(r"[a-z]", password):
        problems.append("a lowercase letter")
    if not re.search(r"[0-9]", password):
        problems.append("a number")
    return problems


def password_strength(password):
    """0-4 strength estimate for the meter."""
    if not password:
        return 0
    score = 0
    score += len(password) >= MIN_PASSWORD_LENGTH
    score += len(password) >= 12
    score += bool(re.search(r"[A-Z]", password) and re.search(r"[a-z]", password))
    score += bool(re.search(r"[0-9]", password))
    score += bool(re.search(r"[^A-Za-z0-9]", password))
    return min(4, score)


def normalise_mobile(mobile):
    mobile = re.sub(r"[\s-]", "", mobile or "")
    if mobile and not mobile.startswith("+") and len(mobile) == 10:
        mobile = "+91" + mobile          # Indian mobile without country code
    return mobile


def _locked(method):
    """users.json is shared with the web API: read, change and save it as one step."""
    @wraps(method)
    def wrapper(*args, **kwargs):
        with file_lock(USERS_FILE):
            return method(*args, **kwargs)
    return wrapper


class AuthManager:
    """
    Prototype local role-based authentication.

    Production: FastAPI + PostgreSQL, sessions/JWT, HTTPS, audit logs.
    Passwords are salted PBKDF2 hashes – never stored in plain text.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_store()

    @_locked
    def _ensure_store(self):
        if USERS_FILE.exists():
            return
        # A hosted copy sets HEAT_ADMIN_PASSWORD so the public site never has the
        # prototype password; on a desktop it stays Admin@123 (see README).
        salt, digest = _hash_password(os.environ.get("HEAT_ADMIN_PASSWORD") or "Admin@123")
        self._write({"users": [{
            "username": "admin",
            "full_name": "System Administrator",
            "designation": "System Admin",
            "role": "admin",
            "city": "Tamil Nadu",
            "district": "",
            "mobile": "",
            "active": True,
            "salt": salt,
            "password_hash": digest,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }]})

    def _read(self):
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))

    def _write(self, data):
        atomic_write_text(USERS_FILE, json.dumps(data, indent=2))

    def _find(self, data, username):
        for user in data["users"]:
            if user["username"].lower() == username.lower():
                return user
        return None

    # ---------------------------------------------------------------- login
    @_locked
    def authenticate(self, username, password, role):
        """Returns (user or None, error message)."""
        generic = "Sign-in failed. Check the access type, login ID and password."
        data = self._read()
        user = self._find(data, username)
        if user is None:
            return None, generic

        locked_until = user.get("locked_until", 0)
        if locked_until > time.time():
            wait = int(locked_until - time.time()) + 1
            return None, f"Too many failed attempts. Try again in {wait} seconds."

        _, digest = _hash_password(password, user["salt"])
        ok = secrets.compare_digest(digest, user["password_hash"]) and user["role"] == role
        if not ok:
            user["failed_attempts"] = user.get("failed_attempts", 0) + 1
            remaining = MAX_FAILED_ATTEMPTS - user["failed_attempts"]
            message = generic
            if user["failed_attempts"] >= MAX_FAILED_ATTEMPTS:
                user["locked_until"] = time.time() + LOCKOUT_SECONDS
                user["failed_attempts"] = 0
                message = f"Too many failed attempts. This account is locked for {LOCKOUT_SECONDS} seconds."
            elif remaining <= 2:
                message = f"{generic} {remaining} attempt{'s' if remaining != 1 else ''} left before a short lock."
            self._write(data)
            return None, message

        if not user.get("active", True):
            return None, "This account has been deactivated. Contact your System Admin."

        user["failed_attempts"] = 0
        user["locked_until"] = 0
        user["last_login"] = datetime.now().isoformat(timespec="seconds")
        self._write(data)
        return user, ""

    def login(self, username, password, role):
        """Backwards compatible: returns the user or None."""
        return self.authenticate(username, password, role)[0]

    # ------------------------------------------------------------- accounts
    @_locked
    def create_city_admin(self, username, password, city, full_name="", designation="",
                          district="", mobile=""):
        username = username.strip()
        if not USERNAME_PATTERN.match(username):
            raise ValueError("Login ID must be 3–32 characters: letters, numbers, dot, dash or underscore.")
        if not city.strip():
            raise ValueError("City / authority is required.")
        problems = password_problems(password)
        if problems:
            raise ValueError("Password needs " + ", ".join(problems) + ".")
        mobile = normalise_mobile(mobile)
        if mobile and not MOBILE_PATTERN.match(mobile):
            raise ValueError("Mobile number should be 10 digits (or include the country code, e.g. +91…).")

        data = self._read()
        if self._find(data, username):
            raise ValueError("That login ID already exists.")

        salt, digest = _hash_password(password)
        data["users"].append({
            "username": username,
            "full_name": full_name.strip(),
            "designation": designation.strip(),
            "role": "city_admin",
            "city": city.strip(),
            "district": district.strip(),
            "mobile": mobile,
            "active": True,
            "salt": salt,
            "password_hash": digest,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        self._write(data)

    @_locked
    def set_active(self, username, active):
        data = self._read()
        user = self._find(data, username)
        if user is None:
            raise ValueError("Account not found.")
        if user["role"] == "admin" and not active:
            raise ValueError("The System Admin account cannot be deactivated here.")
        user["active"] = bool(active)
        self._write(data)

    @_locked
    def reset_password(self, username, new_password):
        problems = password_problems(new_password)
        if problems:
            raise ValueError("Password needs " + ", ".join(problems) + ".")
        data = self._read()
        user = self._find(data, username)
        if user is None:
            raise ValueError("Account not found.")
        user["salt"], user["password_hash"] = _hash_password(new_password)
        user["failed_attempts"], user["locked_until"] = 0, 0
        self._write(data)

    def list_users(self):
        return [{k: v for k, v in u.items() if k not in ("salt", "password_hash")}
                for u in self._read()["users"]]

    def list_city_admins(self):
        return [u for u in self.list_users() if u["role"] == "city_admin"]

    def recipients_for(self, district):
        """Active city administrators assigned to a district (for alerts)."""
        return [u for u in self.list_city_admins()
                if u.get("active", True) and u.get("district", "").lower() == district.lower()]
