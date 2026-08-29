"""Authentication blueprint and user store backed by a local JSON file."""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque

from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config

auth_bp = Blueprint("auth", __name__)


# ---------------------------------------------------------------------------
# Login rate limiting – simple in-memory sliding window keyed by client IP.
#
# This is intentionally lightweight (no extra dependency, no external store)
# to match the rest of the app's single-process, in-memory state (see
# UserStore / PeerNameStore). It resets on restart, which is an acceptable
# trade-off for a homelab-scale deployment behind a single process.
#
# The attempt/window thresholds are read from `current_app.config` (populated
# from Config at app-creation time) rather than from the Config class
# directly, so per-app overrides (e.g. in tests) are respected correctly.
# ---------------------------------------------------------------------------

_login_attempts: dict[str, deque] = defaultdict(deque)
_login_attempts_lock = threading.Lock()


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def _is_rate_limited(key: str) -> bool:
    """Return True if *key* has exceeded the allowed failed attempts."""
    now = time.time()
    window = current_app.config.get(
        "LOGIN_RATE_LIMIT_WINDOW_SECONDS", Config.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    )
    limit = current_app.config.get(
        "LOGIN_RATE_LIMIT_ATTEMPTS", Config.LOGIN_RATE_LIMIT_ATTEMPTS
    )
    with _login_attempts_lock:
        attempts = _login_attempts[key]
        while attempts and now - attempts[0] > window:
            attempts.popleft()
        return len(attempts) >= limit


def _record_failed_attempt(key: str) -> None:
    with _login_attempts_lock:
        _login_attempts[key].append(time.time())


def _clear_attempts(key: str) -> None:
    with _login_attempts_lock:
        _login_attempts.pop(key, None)


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------


class User(UserMixin):
    """A user account with a stored Werkzeug password hash."""

    def __init__(self, username: str, password_hash: str):
        self.id = username
        self.username = username
        self._password_hash = password_hash

    def check_password(self, password: str) -> bool:
        return check_password_hash(self._password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.username}>"


# ---------------------------------------------------------------------------
# UserStore – persists accounts to a JSON file
# ---------------------------------------------------------------------------


class UserStore:
    """Thread-safe store for user accounts saved as hashed passwords in a JSON file.

    On first use the file is created and seeded with the admin credentials
    taken from ``Config.ADMIN_USERNAME`` / ``Config.ADMIN_PASSWORD``.
    """

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._users: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read users from *filepath*; seed with admin credentials if empty."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath) as fh:
                    self._users = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._users = {}

        if not self._users:
            self._users = {
                Config.ADMIN_USERNAME: {
                    "password_hash": generate_password_hash(Config.ADMIN_PASSWORD)
                }
            }
            self._save()

    def _save(self) -> None:
        """Write current user data to *filepath* (caller must hold ``_lock``)."""
        with open(self.filepath, "w") as fh:
            json.dump(self._users, fh, indent=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_user(self, username: str) -> User | None:
        """Return a :class:`User` for *username*, or ``None`` if not found."""
        with self._lock:
            data = self._users.get(username)
        if data:
            return User(username, data["password_hash"])
        return None

    def list_users(self) -> list[str]:
        """Return an alphabetically sorted list of all usernames."""
        with self._lock:
            return sorted(self._users.keys())

    def create_user(self, username: str, password: str) -> bool:
        """Create *username* with *password*.  Returns ``False`` if already exists."""
        with self._lock:
            if username in self._users:
                return False
            self._users[username] = {
                "password_hash": generate_password_hash(password)
            }
            self._save()
        return True

    def change_password(self, username: str, new_password: str) -> bool:
        """Update password for *username*.  Returns ``False`` if user not found."""
        with self._lock:
            if username not in self._users:
                return False
            self._users[username]["password_hash"] = generate_password_hash(new_password)
            self._save()
        return True

    def delete_user(self, username: str) -> bool:
        """Remove *username*.  Returns ``False`` if user not found."""
        with self._lock:
            if username not in self._users:
                return False
            del self._users[username]
            self._save()
        return True


# ---------------------------------------------------------------------------
# Module-level singleton (lazy-initialised)
# ---------------------------------------------------------------------------

_user_store: UserStore | None = None
_store_lock = threading.Lock()


def get_user_store() -> UserStore:
    """Return the application-wide :class:`UserStore` singleton."""
    global _user_store
    if _user_store is None:
        with _store_lock:
            if _user_store is None:
                _user_store = UserStore(Config.USERS_FILE)
    return _user_store


def load_user(user_id: str) -> User | None:
    """Flask-Login user-loader callback."""
    return get_user_store().get_user(user_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        client_key = _client_ip()
        if _is_rate_limited(client_key):
            flash("Too many failed login attempts. Please try again later.", "danger")
            return render_template("login.html"), 429

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        store = get_user_store()
        user = store.get_user(username)
        if user and user.check_password(password):
            _clear_attempts(client_key)
            login_user(user, remember=True)
            next_page = request.args.get("next") or url_for("main.dashboard")
            return redirect(next_page)
        _record_failed_attempt(client_key)
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
