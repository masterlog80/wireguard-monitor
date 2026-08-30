"""Flask application factory."""
from __future__ import annotations

from flask import Flask, flash, jsonify, redirect, request, url_for
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError

from config import Config
from .auth import User, load_user

csrf = CSRFProtect()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

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
