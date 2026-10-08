import os
import secrets


def _bool_env(name: str, default: bool) -> bool:
    """Parse a boolean environment variable ('1', 'true', 'yes' -> True)."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
    # Default admin credentials (override via env vars in production)
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
    # How many historical data-points to keep per peer (5s interval × 60 = 5 min)
    MAX_HISTORY = int(os.environ.get("MAX_HISTORY", 60))
    # Maximum number of points returned to the dashboard per graph. The full
    # MAX_HISTORY remains retained in memory; this only reduces chart density.
    CHART_MAX_POINTS = int(os.environ.get("CHART_MAX_POINTS", 30))
    # WireGuard interface (leave empty to auto-detect)
    WG_INTERFACE = os.environ.get("WG_INTERFACE", "")
    # Path to the JSON file used to persist user accounts with hashed passwords
    USERS_FILE = os.environ.get("USERS_FILE", "users.json")
    # Path to the JSON file used to persist peer display names
    PEER_NAMES_FILE = os.environ.get("PEER_NAMES_FILE", "peer_names.json")
    # Directory where saved firewall rule snapshots are stored
    FIREWALL_SAVE_DIR = os.environ.get("FIREWALL_SAVE_DIR", "firewall_saves")

    # --- Session / cookie hardening ---
    # Cookies are never readable from JS and default to SameSite=Lax, which
    # blocks the cookie being sent on cross-site POSTs. Set SESSION_COOKIE_SECURE=true
    # once the app is served over HTTPS (e.g. behind a reverse proxy).
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = _bool_env("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    REMEMBER_COOKIE_SECURE = _bool_env("SESSION_COOKIE_SECURE", False)

    # --- CSRF protection (Flask-WTF) ---
    # Kept on by default; tests disable it explicitly so the existing
    # test client requests (which don't carry a CSRF token) keep working.
    WTF_CSRF_ENABLED = _bool_env("WTF_CSRF_ENABLED", True)
    # This is a long-running, auto-refreshing dashboard people routinely leave
    # open for hours -- the CSRF token embedded in the page at load time is
    # never refreshed client-side, so Flask-WTF's 3600s (1 hour) default
    # would silently break every button (Save, Restart, rename, ...) on any
    # session left open longer than that, surfacing as a confusing "<!doctype
    # ..." is not valid JSON" error in the browser console. None ties the
    # token's validity to the session itself instead of a separate clock.
    _csrf_time_limit_env = os.environ.get("WTF_CSRF_TIME_LIMIT")
    WTF_CSRF_TIME_LIMIT = int(_csrf_time_limit_env) if _csrf_time_limit_env else None

    # --- Login rate limiting ---
    # Max failed login attempts allowed from a single IP within the window
    # before further attempts are rejected with 429.
    LOGIN_RATE_LIMIT_ATTEMPTS = int(os.environ.get("LOGIN_RATE_LIMIT_ATTEMPTS", 10))
    LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(
        os.environ.get("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300)
    )

    # --- Request size limit ---
    # Caps the size of any incoming request body (JSON payloads and file
    # uploads: WireGuard/firewall config import). Prevents a logged-in user
    # (or a leaked session) from exhausting memory with an oversized upload.
    # Default 16 MiB comfortably covers WireGuard/iptables/nftables configs.
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))

    # --- Password policy ---
    # Minimum length enforced when creating a user or changing a password.
    MIN_PASSWORD_LENGTH = int(os.environ.get("MIN_PASSWORD_LENGTH", 8))
