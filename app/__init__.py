"""Flask application factory."""
from __future__ import annotations

import os
from datetime import datetime

from flask import Flask, flash, jsonify, redirect, request, url_for
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError

from config import Config
from .auth import User, load_user

csrf = CSRFProtect()

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_app_version() -> str:
    """Read the app version from the VERSION file at the repo root.

    Resolved relative to this file's own location rather than the process's
    current working directory, so it works the same regardless of how/where
    the app is launched from (unlike a couple of the path defaults this
    project has been bitten by before). Falls back to "unknown" if the file
    is missing or unreadable rather than failing app startup over it.
    """
    try:
        with open(os.path.join(_REPO_ROOT, "VERSION")) as f:
            return f.read().strip() or "unknown"
    except OSError:
        return "unknown"


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["VERSION"] = get_app_version()
    app.jinja_env.globals["app_version"] = app.config["VERSION"]
    # Display the process start time in the shared UI footer, using server-local
    # time so it matches the host's operational conventions.
    app.jinja_env.globals["app_start_time"] = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    # --- CSRF protection for all state-changing requests (forms + JSON APIs) ---
    csrf.init_app(app)

    @app.errorhandler(CSRFError)
    def _handle_csrf_error(e: CSRFError):
        """Return JSON for API calls instead of Flask-WTF's default HTML
        error page, which breaks every fetch()-based button on the site
        with a confusing "<!doctype ..." is not valid JSON" console error
        instead of a readable message (see api_firewall_save and friends,
        all of which use fetchWithCsrf() and expect a JSON response back
        no matter what).
        """
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": f"Security check failed: {e.description}. Please refresh the page and try again."}), 400
        flash(f"Security check failed: {e.description}. Please try again.", "danger")
        return redirect(request.referrer or url_for("auth.login"))

    # --- Flask-Login setup ---
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"  # type: ignore[assignment]
    login_manager.login_message_category = "info"
    login_manager.init_app(app)

    @login_manager.user_loader
    def _load_user(user_id: str):
        return load_user(user_id)

    # --- Register blueprints ---
    from .routes import main_bp
    from .auth import auth_bp
    from .users import users_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)

    # --- Start background poller ---
    from . import wireguard

    wireguard.start_poller(interval=5.0)

    return app
