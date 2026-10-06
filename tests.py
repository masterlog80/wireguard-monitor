"""Basic tests for the WireGuard Monitor web application."""
import importlib
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure the repo root is importable
_PROJECT_ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(_PROJECT_ROOT))

# Use a fixed secret key for tests and a temp users file
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "testpass")
os.environ["USERS_FILE"] = "/tmp/test_users_wireguard.json"
os.environ["PEER_NAMES_FILE"] = "/tmp/test_peer_names_wireguard.json"
# The test client doesn't attach CSRF tokens to its requests, so disable
# CSRF enforcement for the test suite (dedicated tests below exercise it
# explicitly with WTF_CSRF_ENABLED re-enabled on a scoped app instance).
os.environ.setdefault("WTF_CSRF_ENABLED", "false")


def _reset_user_store():
    """Remove temp users file and reset the module-level singleton."""
    import app.auth as auth_mod
    auth_mod._user_store = None
    try:
        os.remove("/tmp/test_users_wireguard.json")
    except FileNotFoundError:
        pass


def _reset_peer_name_store():
    """Remove temp peer names file and reset the module-level singleton."""
    import app.peer_names as pn_mod
    pn_mod._peer_name_store = None
    try:
        os.remove("/tmp/test_peer_names_wireguard.json")
    except FileNotFoundError:
        pass


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        import config
        importlib.reload(config)
        from config import Config
        self.assertIsNotNone(Config.SECRET_KEY)
        self.assertEqual(Config.ADMIN_USERNAME, "admin")

    def test_csrf_token_has_no_default_time_limit(self):
        """This is a long-running, auto-refreshing dashboard people leave
        open for hours -- the page's CSRF token is never refreshed
        client-side, so it must not expire on Flask-WTF's default 1-hour
        clock or every button breaks on any session left open longer than
        that."""
        import config
        importlib.reload(config)
        from config import Config
        self.assertIsNone(Config.WTF_CSRF_TIME_LIMIT)


class TestAppVersion(unittest.TestCase):
    def test_reads_version_file(self):
        from app import get_app_version

        version = get_app_version()
        # Loosely validate it looks like a version string rather than
        # pinning the exact value, which will change over time.
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_falls_back_when_version_file_missing(self):
        from app import get_app_version

        with patch("builtins.open", side_effect=OSError("no such file")):
            self.assertEqual(get_app_version(), "unknown")


class TestInstallScript(unittest.TestCase):
    """install.sh isn't Python, so these are lightweight structural checks
    rather than behavioral tests: valid syntax, and the two capabilities
    this script exists for (GitHub token auth, pending-PR selection) are
    actually present."""

    def setUp(self):
        self.script_path = _PROJECT_ROOT / "install.sh"

    def test_exists_and_is_executable(self):
        self.assertTrue(self.script_path.is_file())
        self.assertTrue(os.access(self.script_path, os.X_OK))

    def test_valid_bash_syntax(self):
        import subprocess

        result = subprocess.run(
            ["bash", "-n", str(self.script_path)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_has_github_token_auth_and_pending_pr_selection(self):
        content = self.script_path.read_text()
        # Token auth: reads from env, falls back to an interactive prompt.
        self.assertIn("GH_TOKEN", content)
        self.assertIn("GITHUB_TOKEN", content)
        self.assertIn("read -s -p", content)
        # Pending PR selection: lists open, non-draft PRs and lets the
        # user pick one as the clone ref instead of main.
        self.assertIn("pulls?state=open", content)
        self.assertIn("draft == false", content)
        self.assertIn("CLONE_REF", content)


class TestAppFactory(unittest.TestCase):
    def setUp(self):
        # Remove any leftover temp users file and reset the singleton
        _reset_user_store()
        from app import create_app
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        _reset_user_store()

    def test_login_page_loads(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"WireGuard Monitor", resp.data)

    def test_redirect_to_login_when_unauthenticated(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn("/login", resp.headers.get("Location", ""))

    def test_login_with_wrong_credentials(self):
        resp = self.client.post(
            "/login",
            data={"username": "admin", "password": "wrongpassword"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Invalid username or password", resp.data)

    def test_login_with_correct_credentials(self):
        resp = self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        # Should land on dashboard
        self.assertIn(b"WireGuard", resp.data)

    def test_navbar_shows_username_and_theme_toggle(self):
        resp = self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"admin", resp.data)
        self.assertIn(b'id="theme-toggle-btn"', resp.data)

    def test_footer_shows_app_version(self):
        from app import get_app_version

        expected = f"v{get_app_version()}".encode()

        resp = self.client.get("/login")
        self.assertIn(expected, resp.data)

        self.client.post(
            "/login", data={"username": "admin", "password": "testpass"}
        )
        resp = self.client.get("/")
        self.assertIn(expected, resp.data)

    def test_api_status_includes_version(self):
        from app import get_app_version

        self.client.post(
            "/login", data={"username": "admin", "password": "testpass"}
        )
        resp = self.client.get("/api/status")
        self.assertEqual(resp.get_json()["version"], get_app_version())

    def test_login_page_has_no_theme_toggle(self):
        # The toggle only makes sense once a user (and their preference) exist
        # in the authenticated shell; the standalone login page omits it.
        resp = self.client.get("/login")
        self.assertNotIn(b'id="theme-toggle-btn"', resp.data)

    def _login(self):
        self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
        )

    def test_dashboard_requires_login(self):
        resp = self.client.get("/")
        self.assertIn(resp.status_code, (301, 302))

    def test_dashboard_after_login(self):
        self._login()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Dashboard", resp.data)

    def test_firewall_page_after_login(self):
        self._login()
        resp = self.client.get("/firewall")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Firewall", resp.data)

    def test_options_page_requires_login(self):
        resp = self.client.get("/options")
        self.assertIn(resp.status_code, (301, 302))

    def test_options_page_after_login(self):
        self._login()
        resp = self.client.get("/options")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Peer View", resp.data)
        self.assertIn(b'id="peer-perspective-list"', resp.data)

    def test_dashboard_supports_manual_graph_ordering(self):
        """Throughput and Ping graph order must be draggable and persisted."""
        dashboard_js = (
            _PROJECT_ROOT / "app" / "static" / "js" / "dashboard.js"
        ).read_text()
        dashboard_html = (
            _PROJECT_ROOT / "app" / "templates" / "dashboard.html"
        ).read_text()

        self.assertIn("CHART_ORDER_STORAGE_KEYS", dashboard_js)
        self.assertIn("installChartOrdering", dashboard_js)
        self.assertIn("saveChartOrder", dashboard_js)
        self.assertIn("draggable", dashboard_js)
        self.assertIn("peer-chart-drag-handle", dashboard_js)
        self.assertIn("Drag graphs to reorder", dashboard_html)
        self.assertIn("reset-chart-order-btn", dashboard_html)
        self.assertIn("reset-chart-order-btn", dashboard_js)

    def test_perspective_toggle_moved_out_of_dashboard_js(self):
        """Regression test for moving the per-peer "Peer view" toggle off
        the Dashboard's Throughput cards and onto the Options page: the
        old per-graph button/badge markup and its click handler must be
        gone from dashboard.js, and the shared perspective-map helpers
        must live in options.js instead."""
        dashboard_js = (
            _PROJECT_ROOT / "app" / "static" / "js" / "dashboard.js"
        ).read_text()
        for stale in ("perspective-toggle-btn", "peer-perspective-badge", "togglePeerPerspective"):
            self.assertNotIn(stale, dashboard_js)

        options_js = (_PROJECT_ROOT / "app" / "static" / "js" / "options.js").read_text()
        self.assertIn("peer-perspective-switch", options_js)

    def test_api_status_after_login(self):
        self._login()
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("available", data)

    def test_api_peers_after_login(self):
        self._login()
        resp = self.client.get("/api/peers")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.get_json(), list)

    def test_api_throughput_after_login(self):
        self._login()
        resp = self.client.get("/api/throughput")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.get_json(), dict)

    def test_api_ping_after_login(self):
        self._login()
        resp = self.client.get("/api/ping")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.get_json(), dict)

    def test_api_restart_requires_login(self):
        resp = self.client.post("/api/restart", follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn("/login", resp.headers.get("Location", ""))

    def test_api_restart_no_interfaces(self):
        """When no WireGuard interfaces are found, restart returns 400."""
        from app import wireguard
        self._login()
        with patch.object(wireguard, "get_interfaces", return_value=[]):
            resp = self.client.post("/api/restart")
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["ok"])

    def test_api_restart_success(self):
        """A successful systemctl restart returns ok=True."""
        from app import wireguard
        self._login()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch.object(wireguard, "get_interfaces", return_value=["wg0"]), \
             patch("app.routes.subprocess.run", return_value=mock_result):
            resp = self.client.post("/api/restart")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("wg0", data["restarted"])

    def test_api_restart_failure(self):
        """A failed systemctl restart returns ok=False with an error."""
        from app import wireguard
        self._login()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Failed to restart"
        with patch.object(wireguard, "get_interfaces", return_value=["wg0"]), \
             patch("app.routes.subprocess.run", return_value=mock_result):
            resp = self.client.post("/api/restart")
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("wg0", data["error"])

    def test_api_restart_invalid_interface_name(self):
        """An interface name with invalid characters is rejected."""
        from app import wireguard
        self._login()
        with patch.object(wireguard, "get_interfaces", return_value=["wg0; rm -rf /"]):
            resp = self.client.post("/api/restart")
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("Invalid interface name", data["error"])

    def test_logout(self):
        self._login()
        resp = self.client.get("/logout", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"logged out", resp.data)


class TestWireguardParser(unittest.TestCase):
    def test_parse_interface_block(self):
        from app.wireguard import _parse_interface_block

        sample = """interface: wg0
  public key: abcdefghijklmnopqrstuvwxyz123456
  listening port: 51820

peer: PEERPUBKEY1234567890abcdefghijklmnop
  endpoint: 1.2.3.4:51820
  allowed ips: 10.0.0.2/32
  latest handshake: 1 minute, 30 seconds ago
  transfer: 1.23 MiB received, 456 KiB sent
"""
        result = _parse_interface_block("wg0", sample)
        self.assertEqual(result["name"], "wg0")
        self.assertEqual(result["listening_port"], "51820")
        self.assertEqual(len(result["peers"]), 1)
        self.assertEqual(result["peers"][0]["endpoint"], "1.2.3.4:51820")

    def test_get_wg_status_no_wg(self):
        """When wg binary is not available the status should reflect unavailable."""
        from app import wireguard

        with patch.object(wireguard, "_run", return_value=(1, "", "not found")):
            status = wireguard.get_wg_status()
        self.assertFalse(status["available"])

    def test_get_peers_parses_dump(self):
        from app import wireguard

        dump_output = (
            "privatekey\tpubkey_iface\t0.0.0.0:51820\t0\n"
            "pubkey1\t(none)\t10.0.0.1:12345\t10.0.0.2/32\t{ts}\t102400\t51200\t0\n".format(
                ts=int(time.time()) - 30
            )
        )

        def fake_run(cmd):
            if "interfaces" in cmd:
                return (0, "wg0\n", "")
            if "dump" in cmd:
                return (0, dump_output, "")
            return (1, "", "")

        with patch.object(wireguard, "_run", side_effect=fake_run):
            peers = wireguard.get_peers()

        self.assertEqual(len(peers), 1)
        self.assertTrue(peers[0]["connected"])
        self.assertEqual(peers[0]["rx_bytes"], 102400)

    def test_get_peers_skips_malformed_transfer_counters(self):
        """A peer row with non-numeric rx/tx should be skipped, not raise."""
        from app import wireguard

        dump_output = (
            "privatekey\tpubkey_iface\t0.0.0.0:51820\t0\n"
            "pubkey_bad\t(none)\t10.0.0.1:12345\t10.0.0.2/32\t{ts}\tnot-a-number\t51200\t0\n"
            "pubkey_good\t(none)\t10.0.0.3:12345\t10.0.0.4/32\t{ts}\t2048\t1024\t0\n".format(
                ts=int(time.time()) - 30
            )
        )

        def fake_run(cmd):
            if "interfaces" in cmd:
                return (0, "wg0\n", "")
            if "dump" in cmd:
                return (0, dump_output, "")
            return (1, "", "")

        with patch.object(wireguard, "_run", side_effect=fake_run):
            peers = wireguard.get_peers()

        # The malformed row is skipped; the well-formed one still parses.
        self.assertEqual(len(peers), 1)
        self.assertEqual(peers[0]["public_key"], "pubkey_good")
        self.assertEqual(peers[0]["rx_bytes"], 2048)

    def test_throughput_history_calculation(self):
        from app import wireguard

        key = "testkey"
        now = time.time()
        with wireguard._history_lock:
            wireguard._peer_history[key] = __import__("collections").deque(maxlen=60)
            wireguard._peer_history[key].append((now - 5, 0, 0, True))
            wireguard._peer_history[key].append((now, 5000, 2500, True))

        hist = wireguard.get_throughput_history()
        self.assertIn(key, hist)
        self.assertEqual(len(hist[key]["rx_bps"]), 1)
        self.assertAlmostEqual(hist[key]["rx_bps"][0], 1000.0, delta=10)

    def test_throughput_suppressed_while_disconnected(self):
        """A byte-counter delta spanning a disconnected endpoint should be
        reported as zero, not a real rate.

        WireGuard can report a slow trickle of "sent" bytes for a peer with
        no recent handshake -- see the reported case of a peer showing
        continuous TX with a 3-day-stale handshake, confirmed via `wg show
        wg0 transfer` directly (bypassing the app). That's real WireGuard
        data, but not meaningful as this peer's throughput, so it shouldn't
        render as an active-looking chart line.
        """
        from app import wireguard

        key = "disconnected_peer"
        now = time.time()
        with wireguard._history_lock:
            wireguard._peer_history[key] = __import__("collections").deque(maxlen=60)
            # Raw counters genuinely increasing (like the real-world case),
            # but the peer is disconnected at both ends of this interval.
            wireguard._peer_history[key].append((now - 5, 1000, 2000, False))
            wireguard._peer_history[key].append((now, 1200, 2050, False))

        hist = wireguard.get_throughput_history()
        self.assertEqual(hist[key]["rx_bps"], [0.0])
        self.assertEqual(hist[key]["tx_bps"], [0.0])

    def test_throughput_shown_across_reconnection(self):
        """A genuine reconnection (disconnected -> connected) should still
        report zero for that transitional interval, since it spans a period
        with no live handshake -- only fully-connected intervals get a real
        rate."""
        from app import wireguard

        key = "reconnecting_peer"
        now = time.time()
        with wireguard._history_lock:
            wireguard._peer_history[key] = __import__("collections").deque(maxlen=60)
            wireguard._peer_history[key].append((now - 10, 0, 0, False))
            wireguard._peer_history[key].append((now - 5, 100, 100, True))
            wireguard._peer_history[key].append((now, 5100, 2600, True))

        hist = wireguard.get_throughput_history()
        # First interval spans disconnected -> connected: suppressed.
        self.assertEqual(hist[key]["rx_bps"][0], 0.0)
        # Second interval is fully connected: real rate.
        self.assertAlmostEqual(hist[key]["rx_bps"][1], 1000.0, delta=10)

    def test_ping_history_skips_disconnected_peers(self):
        """Disconnected peers must not be actively pinged.

        Regression test: pinging an already-disconnected peer sends real
        traffic through the WireGuard interface toward that peer's IP,
        which can itself show up as phantom throughput on a peer the
        dashboard is simultaneously reporting as Disconnected -- see
        README/issue discussion. A (timestamp, None) gap should still be
        recorded so the ping chart's timeline stays continuous.
        """
        from app import wireguard

        wireguard._ping_history.clear()
        connected_peer = {
            "public_key": "connected_pub",
            "allowed_ips": "10.0.0.2/32",
            "connected": True,
        }
        disconnected_peer = {
            "public_key": "disconnected_pub",
            "allowed_ips": "10.0.0.4/32",
            "connected": False,
        }

        with patch.object(wireguard, "ping_peer", return_value=12.5) as mock_ping:
            wireguard._update_ping_history([connected_peer, disconnected_peer])

        # Only the connected peer's IP should ever have been pinged.
        mock_ping.assert_called_once_with("10.0.0.2")

        hist = wireguard.get_ping_history()
        self.assertEqual(hist["connected_pub"]["latencies"], [12.5])
        self.assertEqual(hist["disconnected_pub"]["latencies"], [None])


class TestFirewall(unittest.TestCase):
    def test_parse_iptables_output(self):
        from app.firewall import _parse_iptables_output

        sample = """Chain INPUT (policy ACCEPT 1234 packets, 5678 bytes)
 pkts bytes target     prot opt in     out     source               destination
    0     0 ACCEPT     all  --  *      *       0.0.0.0/0            0.0.0.0/0

Chain FORWARD (policy DROP 0 packets, 0 bytes)
Chain OUTPUT (policy ACCEPT 42 packets, 1024 bytes)
"""
        result = _parse_iptables_output(sample)
        self.assertIn("chains", result)
        self.assertIn("INPUT", result["chains"])
        self.assertIn("FORWARD", result["chains"])

    def test_get_firewall_rules_keys(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(1, "", "permission denied")):
            rules = firewall.get_firewall_rules()

        self.assertIn("iptables", rules)
        self.assertIn("nftables", rules)

    def test_save_iptables_rules_success(self):
        from app import firewall

        mock_stat = MagicMock()
        mock_stat.st_mtime = 1000000.0
        with patch.object(firewall, "_run", return_value=(0, "*filter\nCOMMIT\n", "")), \
             patch("builtins.open", unittest.mock.mock_open()), \
             patch.object(firewall, "_ensure_save_dir", return_value="/tmp"), \
             patch("app.firewall.os.stat", return_value=mock_stat):
            result = firewall.save_iptables_rules()

        self.assertTrue(result["ok"])
        self.assertEqual(result["saved_at"], 1000000.0)

    def test_save_iptables_rules_failure(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(1, "", "permission denied")):
            result = firewall.save_iptables_rules()

        self.assertFalse(result["ok"])
        self.assertIn("permission denied", result["error"])

    def test_save_iptables_rules_handles_unwritable_save_dir(self):
        """Regression test: on a hardened systemd deployment, the default
        FIREWALL_SAVE_DIR can resolve to a read-only path (see
        wireguard-monitor.service's ProtectSystem=strict). Previously
        os.makedirs() failing here wasn't caught, causing an unhandled 500
        -- surfaced in the browser as "Unexpected token '<' ... is not
        valid JSON" instead of a readable error, since Flask's default
        error page is HTML and every Save/Restore button expects JSON.
        """
        from app import firewall

        with patch.object(firewall, "_run", return_value=(0, "*filter\nCOMMIT\n", "")), \
             patch.object(firewall, "_ensure_save_dir", side_effect=PermissionError("Read-only file system")):
            result = firewall.save_iptables_rules()

        self.assertFalse(result["ok"])
        self.assertIn("Read-only file system", result["error"])

    def test_restore_iptables_rules_no_file(self):
        from app import firewall

        with patch.object(firewall, "os") as mock_os:
            mock_os.path.exists.return_value = False
            mock_os.makedirs = os.makedirs
            mock_os.stat = os.stat
            result = firewall.restore_iptables_rules()

        self.assertFalse(result["ok"])
        self.assertIn("No saved iptables rules found", result["error"])

    def test_restore_iptables_rules_success(self):
        import tempfile
        from app import firewall

        with tempfile.NamedTemporaryFile(mode="w", suffix=".rules", delete=False) as f:
            f.write("*filter\nCOMMIT\n")
            tmp_path = f.name

        try:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stderr = ""
            with patch.object(firewall, "_iptables_save_path", return_value=tmp_path), \
                 patch("app.firewall.subprocess.run", return_value=mock_result):
                result = firewall.restore_iptables_rules()
            self.assertTrue(result["ok"])
        finally:
            os.unlink(tmp_path)

    def test_save_nftables_rules_success(self):
        from app import firewall

        mock_stat = MagicMock()
        mock_stat.st_mtime = 2000000.0
        with patch.object(firewall, "_run", return_value=(0, "table ip filter {}\n", "")), \
             patch("builtins.open", unittest.mock.mock_open()), \
             patch.object(firewall, "_ensure_save_dir", return_value="/tmp"), \
             patch("app.firewall.os.stat", return_value=mock_stat):
            result = firewall.save_nftables_rules()

        self.assertTrue(result["ok"])
        self.assertEqual(result["saved_at"], 2000000.0)

    def test_save_nftables_rules_failure(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(1, "", "nft not available")):
            result = firewall.save_nftables_rules()

        self.assertFalse(result["ok"])

    def test_save_nftables_rules_handles_unwritable_save_dir(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(0, "table ip filter {}\n", "")), \
             patch.object(firewall, "_ensure_save_dir", side_effect=PermissionError("Read-only file system")):
            result = firewall.save_nftables_rules()

        self.assertFalse(result["ok"])
        self.assertIn("Read-only file system", result["error"])

    def test_restore_nftables_rules_no_file(self):
        from app import firewall

        with patch.object(firewall, "os") as mock_os:
            mock_os.path.exists.return_value = False
            mock_os.makedirs = os.makedirs
            mock_os.stat = os.stat
            result = firewall.restore_nftables_rules()

        self.assertFalse(result["ok"])
        self.assertIn("No saved nftables rules found", result["error"])

    def test_restore_nftables_rules_success(self):
        import tempfile
        from app import firewall

        with tempfile.NamedTemporaryFile(mode="w", suffix=".rules", delete=False) as f:
            f.write("table ip filter {}\n")
            tmp_path = f.name

        try:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stderr = ""
            with patch.object(firewall, "_nftables_save_path", return_value=tmp_path), \
                 patch.object(firewall, "_run", return_value=(0, "", "")), \
                 patch("app.firewall.subprocess.run", return_value=mock_result):
                result = firewall.restore_nftables_rules()
            self.assertTrue(result["ok"])
        finally:
            os.unlink(tmp_path)

    def test_restore_rules_handles_unwritable_save_dir(self):
        """Same regression as the save-side tests: resolving the save path
        can itself raise (not just reading the file at that path)."""
        from app import firewall

        with patch.object(firewall, "_iptables_save_path", side_effect=PermissionError("Read-only file system")):
            result = firewall.restore_iptables_rules()
        self.assertFalse(result["ok"])
        self.assertIn("Read-only file system", result["error"])

        with patch.object(firewall, "_nftables_save_path", side_effect=PermissionError("Read-only file system")):
            result = firewall.restore_nftables_rules()
        self.assertFalse(result["ok"])
        self.assertIn("Read-only file system", result["error"])

    def test_get_saved_rules_info_no_files(self):
        from app import firewall

        with patch.object(firewall, "os") as mock_os:
            mock_os.path.exists.return_value = False
            mock_os.makedirs = os.makedirs
            info = firewall.get_saved_rules_info()

        self.assertFalse(info["iptables"]["exists"])
        self.assertFalse(info["nftables"]["exists"])

    def test_get_saved_rules_info_with_files(self):
        import tempfile
        from app import firewall

        with tempfile.NamedTemporaryFile(mode="w", suffix=".rules", delete=False) as f:
            f.write("*filter\nCOMMIT\n")
            tmp_path = f.name

        try:
            with patch.object(firewall, "_iptables_save_path", return_value=tmp_path), \
                 patch.object(firewall, "_nftables_save_path", return_value="/nonexistent/path"):
                info = firewall.get_saved_rules_info()
            self.assertTrue(info["iptables"]["exists"])
            self.assertIn("saved_at", info["iptables"])
            self.assertFalse(info["nftables"]["exists"])
        finally:
            os.unlink(tmp_path)

    def test_get_saved_rules_info_handles_unwritable_save_dir(self):
        """Same regression as the save/restore tests above, but for the
        endpoint the firewall page calls on every load (loadSnapshotInfo())
        -- an unwritable FIREWALL_SAVE_DIR shouldn't 500 the whole page."""
        from app import firewall

        with patch.object(firewall, "_iptables_save_path", side_effect=PermissionError("Read-only file system")), \
             patch.object(firewall, "_nftables_save_path", side_effect=PermissionError("Read-only file system")):
            info = firewall.get_saved_rules_info()

        self.assertFalse(info["iptables"]["exists"])
        self.assertFalse(info["nftables"]["exists"])


class TestFirewallRoutes(unittest.TestCase):
    """Tests for the firewall save/restore API routes."""

    def setUp(self):
        _reset_user_store()
        from app import create_app
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self._login()

    def tearDown(self):
        _reset_user_store()

    def _login(self):
        self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
        )

    def test_saved_info_requires_login(self):
        self.client.get("/logout")
        resp = self.client.get("/api/firewall/saved_info", follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))

    def test_saved_info_returns_keys(self):
        from app import firewall
        with patch.object(firewall, "get_saved_rules_info",
                          return_value={"iptables": {"exists": False},
                                        "nftables": {"exists": False}}):
            resp = self.client.get("/api/firewall/saved_info")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("iptables", data)
        self.assertIn("nftables", data)

    def test_save_iptables(self):
        from app import firewall
        with patch.object(firewall, "save_iptables_rules", return_value={"ok": True, "path": "/tmp/x"}):
            resp = self.client.post("/api/firewall/save", json={"type": "iptables"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_save_nftables(self):
        from app import firewall
        with patch.object(firewall, "save_nftables_rules", return_value={"ok": True, "path": "/tmp/x"}):
            resp = self.client.post("/api/firewall/save", json={"type": "nftables"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_save_both(self):
        from app import firewall
        with patch.object(firewall, "save_iptables_rules", return_value={"ok": True}), \
             patch.object(firewall, "save_nftables_rules", return_value={"ok": True}):
            resp = self.client.post("/api/firewall/save", json={"type": "both"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("iptables", data["results"])
        self.assertIn("nftables", data["results"])

    def test_save_default_type_is_both(self):
        from app import firewall
        with patch.object(firewall, "save_iptables_rules", return_value={"ok": True}) as mock_ipt, \
             patch.object(firewall, "save_nftables_rules", return_value={"ok": True}) as mock_nft:
            resp = self.client.post("/api/firewall/save", json={})
        self.assertEqual(resp.status_code, 200)
        mock_ipt.assert_called_once()
        mock_nft.assert_called_once()

    def test_save_invalid_type(self):
        resp = self.client.post("/api/firewall/save", json={"type": "invalid"})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

    def test_save_failure_returns_500(self):
        from app import firewall
        with patch.object(firewall, "save_iptables_rules",
                          return_value={"ok": False, "error": "permission denied"}):
            resp = self.client.post("/api/firewall/save", json={"type": "iptables"})
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.get_json()["ok"])

    def test_restore_iptables(self):
        from app import firewall
        with patch.object(firewall, "restore_iptables_rules", return_value={"ok": True}):
            resp = self.client.post("/api/firewall/restore", json={"type": "iptables"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_restore_nftables(self):
        from app import firewall
        with patch.object(firewall, "restore_nftables_rules", return_value={"ok": True}):
            resp = self.client.post("/api/firewall/restore", json={"type": "nftables"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_restore_both(self):
        from app import firewall
        with patch.object(firewall, "restore_iptables_rules", return_value={"ok": True}), \
             patch.object(firewall, "restore_nftables_rules", return_value={"ok": True}):
            resp = self.client.post("/api/firewall/restore", json={"type": "both"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_restore_no_file(self):
        from app import firewall
        with patch.object(firewall, "restore_iptables_rules",
                          return_value={"ok": False, "error": "No saved iptables rules found"}):
            resp = self.client.post("/api/firewall/restore", json={"type": "iptables"})
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.get_json()["ok"])

    def test_restore_requires_login(self):
        self.client.get("/logout")
        resp = self.client.post("/api/firewall/restore", json={"type": "both"},
                                follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))

    def test_save_requires_login(self):
        self.client.get("/logout")
        resp = self.client.post("/api/firewall/save", json={"type": "both"},
                                follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))


class TestUserManagement(unittest.TestCase):
    """Tests for the user management blueprint and UserStore."""

    def setUp(self):
        _reset_user_store()
        from app import create_app
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self._login()

    def tearDown(self):
        _reset_user_store()

    def _login(self):
        self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
        )

    # ------------------------------------------------------------------
    # UserStore unit tests
    # ------------------------------------------------------------------

    def test_user_store_seeds_admin(self):
        from app.auth import get_user_store
        store = get_user_store()
        self.assertIn("admin", store.list_users())

    def test_user_store_create_and_get(self):
        from app.auth import get_user_store
        store = get_user_store()
        self.assertTrue(store.create_user("alice", "secret123"))
        user = store.get_user("alice")
        self.assertIsNotNone(user)
        self.assertTrue(user.check_password("secret123"))

    def test_user_store_create_duplicate_fails(self):
        from app.auth import get_user_store
        store = get_user_store()
        store.create_user("bob", "pass1")
        self.assertFalse(store.create_user("bob", "pass2"))

    def test_user_store_change_password(self):
        from app.auth import get_user_store
        store = get_user_store()
        store.create_user("carol", "oldpass")
        self.assertTrue(store.change_password("carol", "newpass"))
        user = store.get_user("carol")
        self.assertTrue(user.check_password("newpass"))
        self.assertFalse(user.check_password("oldpass"))

    def test_user_store_delete(self):
        from app.auth import get_user_store
        store = get_user_store()
        store.create_user("dave", "pass")
        self.assertTrue(store.delete_user("dave"))
        self.assertIsNone(store.get_user("dave"))

    def test_user_store_persists_to_file(self):
        from app.auth import get_user_store, UserStore
        store = get_user_store()
        store.create_user("eve", "pass123")
        # Load a fresh store from the same file
        store2 = UserStore("/tmp/test_users_wireguard.json")
        self.assertIn("eve", store2.list_users())

    # ------------------------------------------------------------------
    # Route tests
    # ------------------------------------------------------------------

    def test_users_page_loads(self):
        resp = self.client.get("/users/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"User Management", resp.data)

    def test_users_page_requires_login(self):
        self.client.get("/logout")
        resp = self.client.get("/users/", follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn("/login", resp.headers.get("Location", ""))

    def test_create_user_via_route(self):
        resp = self.client.post(
            "/users/create",
            data={"username": "frank", "password": "pw123456", "confirm_password": "pw123456"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"frank", resp.data)

    def test_create_user_mismatched_passwords(self):
        resp = self.client.post(
            "/users/create",
            data={"username": "grace", "password": "abcdefgh", "confirm_password": "xyzxyzxy"},
            follow_redirects=True,
        )
        self.assertIn(b"Passwords do not match", resp.data)

    def test_create_user_password_too_short(self):
        resp = self.client.post(
            "/users/create",
            data={"username": "grace", "password": "short1", "confirm_password": "short1"},
            follow_redirects=True,
        )
        self.assertIn(b"at least", resp.data)

    def test_create_duplicate_user(self):
        self.client.post(
            "/users/create",
            data={"username": "heidi", "password": "password1", "confirm_password": "password1"},
        )
        resp = self.client.post(
            "/users/create",
            data={"username": "heidi", "password": "password2", "confirm_password": "password2"},
            follow_redirects=True,
        )
        self.assertIn(b"already exists", resp.data)

    def test_change_password_via_route(self):
        from app.auth import get_user_store
        store = get_user_store()
        store.create_user("ivan", "oldpassword")
        resp = self.client.post(
            "/users/ivan/change-password",
            data={"new_password": "newpassword", "confirm_password": "newpassword"},
            follow_redirects=True,
        )
        self.assertIn(b"updated successfully", resp.data)
        user = store.get_user("ivan")
        self.assertTrue(user.check_password("newpassword"))

    def test_change_password_too_short(self):
        from app.auth import get_user_store
        store = get_user_store()
        store.create_user("kim", "oldpassword")
        resp = self.client.post(
            "/users/kim/change-password",
            data={"new_password": "short1", "confirm_password": "short1"},
            follow_redirects=True,
        )
        self.assertIn(b"at least", resp.data)
        user = store.get_user("kim")
        self.assertTrue(user.check_password("oldpassword"))

    def test_delete_user_via_route(self):
        from app.auth import get_user_store
        store = get_user_store()
        store.create_user("judy", "pw")
        resp = self.client.post(
            "/users/judy/delete",
            follow_redirects=True,
        )
        self.assertIn(b"deleted", resp.data)
        self.assertIsNone(store.get_user("judy"))

    def test_cannot_delete_self(self):
        resp = self.client.post(
            "/users/admin/delete",
            follow_redirects=True,
        )
        self.assertIn(b"cannot delete your own account", resp.data.lower())


class TestPeerNames(unittest.TestCase):
    """Tests for the peer name alias API endpoints."""

    NAMES_FILE = "/tmp/test_peer_names_wireguard.json"

    def setUp(self):
        _reset_user_store()
        _reset_peer_name_store()
        from app import create_app
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self._login()

    def tearDown(self):
        _reset_peer_name_store()
        _reset_user_store()

    def _login(self):
        self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
        )

    def test_get_peer_names_empty(self):
        resp = self.client.get("/api/peer_names")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {})

    def test_set_peer_name(self):
        pubkey = "PUBKEY1234567890abcdef"
        resp = self.client.post(
            f"/api/peer_names/{pubkey}",
            json={"name": "Alice's Laptop"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_get_peer_names_after_set(self):
        pubkey = "PUBKEY1234567890abcdef"
        self.client.post(f"/api/peer_names/{pubkey}", json={"name": "Alice"})
        resp = self.client.get("/api/peer_names")
        data = resp.get_json()
        self.assertEqual(data.get(pubkey), "Alice")

    def test_set_peer_name_empty_rejected(self):
        resp = self.client.post(
            "/api/peer_names/SOMEKEY",
            json={"name": "   "},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

    def test_set_peer_name_too_long_rejected(self):
        resp = self.client.post(
            "/api/peer_names/SOMEKEY",
            json={"name": "x" * 65},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

    def test_delete_peer_name(self):
        pubkey = "PUBKEY1234567890abcdef"
        self.client.post(f"/api/peer_names/{pubkey}", json={"name": "Bob"})
        resp = self.client.delete(f"/api/peer_names/{pubkey}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        names = self.client.get("/api/peer_names").get_json()
        self.assertNotIn(pubkey, names)

    def test_delete_nonexistent_peer_name(self):
        resp = self.client.delete("/api/peer_names/DOESNOTEXIST")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_peer_names_require_login(self):
        self.client.get("/logout")
        resp = self.client.get("/api/peer_names", follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))

    def test_peer_name_persists_to_file(self):
        import app.peer_names as pn_mod
        pubkey = "PERSISTKEY"
        self.client.post(f"/api/peer_names/{pubkey}", json={"name": "Persisted"})
        # Load a new store from the same file
        store2 = pn_mod.PeerNameStore(self.NAMES_FILE)
        self.assertEqual(store2.get(pubkey), "Persisted")


class TestFirewallExportImport(unittest.TestCase):
    """Tests for the firewall export/import helper functions and API routes."""

    def setUp(self):
        _reset_user_store()
        from app import create_app
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self._login()

    def tearDown(self):
        _reset_user_store()

    def _login(self):
        self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
        )

    # ------------------------------------------------------------------
    # firewall.py unit tests
    # ------------------------------------------------------------------

    def test_export_iptables_rules_success(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(0, "*filter\nCOMMIT\n", "")):
            ok, content, error = firewall.export_iptables_rules()

        self.assertTrue(ok)
        self.assertIn("*filter", content)
        self.assertEqual(error, "")

    def test_export_iptables_rules_failure(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(1, "", "iptables-save failed")):
            ok, content, error = firewall.export_iptables_rules()

        self.assertFalse(ok)
        self.assertIn("iptables-save failed", error)

    def test_export_nftables_rules_success(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(0, "table ip filter {}\n", "")):
            ok, content, error = firewall.export_nftables_rules()

        self.assertTrue(ok)
        self.assertIn("table ip filter", content)
        self.assertEqual(error, "")

    def test_export_nftables_rules_failure(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(1, "", "nft not available")):
            ok, content, error = firewall.export_nftables_rules()

        self.assertFalse(ok)
        self.assertIn("nft not available", error)

    def test_import_iptables_rules_success(self):
        from app import firewall

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch("app.firewall.subprocess.run", return_value=mock_result):
            result = firewall.import_iptables_rules("*filter\nCOMMIT\n")

        self.assertTrue(result["ok"])

    def test_import_iptables_rules_failure(self):
        from app import firewall

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Bad rule"
        with patch("app.firewall.subprocess.run", return_value=mock_result):
            result = firewall.import_iptables_rules("bad content")

        self.assertFalse(result["ok"])
        self.assertIn("Bad rule", result["error"])

    def test_import_nftables_rules_success(self):
        from app import firewall

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        # _run is used for flush+backup; subprocess.run is used for the apply step
        with patch.object(firewall, "_run", return_value=(0, "table ip filter {}\n", "")), \
             patch("app.firewall.subprocess.run", return_value=mock_result):
            result = firewall.import_nftables_rules("table ip filter {}\n")

        self.assertTrue(result["ok"])

    def test_import_nftables_rules_failure_with_rollback(self):
        from app import firewall

        mock_fail = MagicMock()
        mock_fail.returncode = 1
        mock_fail.stderr = "syntax error"

        mock_rollback = MagicMock()
        mock_rollback.returncode = 0

        def fake_run_side_effect(*args, **kwargs):
            # First call is the apply step (returns failure), second is rollback
            if not hasattr(fake_run_side_effect, "calls"):
                fake_run_side_effect.calls = 0
            fake_run_side_effect.calls += 1
            return mock_fail if fake_run_side_effect.calls == 1 else mock_rollback

        with patch.object(firewall, "_run", return_value=(0, "table ip filter {}\n", "")), \
             patch("app.firewall.subprocess.run", side_effect=fake_run_side_effect):
            result = firewall.import_nftables_rules("bad nft content")

        self.assertFalse(result["ok"])
        self.assertIn("syntax error", result["error"])

    # ------------------------------------------------------------------
    # restore_nftables_rules refactoring regression test
    # ------------------------------------------------------------------

    def test_restore_nftables_rules_uses_apply_helper(self):
        """restore_nftables_rules should still apply rules correctly after refactor."""
        import tempfile
        from app import firewall

        with tempfile.NamedTemporaryFile(mode="w", suffix=".rules", delete=False) as f:
            f.write("table ip filter {}\n")
            tmp_path = f.name

        try:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stderr = ""
            with patch.object(firewall, "_nftables_save_path", return_value=tmp_path), \
                 patch.object(firewall, "_run", return_value=(0, "", "")), \
                 patch("app.firewall.subprocess.run", return_value=mock_result):
                result = firewall.restore_nftables_rules()
            self.assertTrue(result["ok"])
        finally:
            os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # Route tests
    # ------------------------------------------------------------------

    def test_firewall_export_iptables(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(0, "*filter\nCOMMIT\n", "")):
            resp = self.client.get("/api/firewall/export?type=iptables")

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"*filter", resp.data)
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))
        self.assertIn("iptables.rules", resp.headers.get("Content-Disposition", ""))

    def test_firewall_export_nftables(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(0, "table ip filter {}\n", "")):
            resp = self.client.get("/api/firewall/export?type=nftables")

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"table ip filter", resp.data)
        self.assertIn("nftables.rules", resp.headers.get("Content-Disposition", ""))

    def test_firewall_export_invalid_type(self):
        resp = self.client.get("/api/firewall/export?type=both")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

    def test_firewall_export_requires_login(self):
        self.client.get("/logout")
        resp = self.client.get("/api/firewall/export?type=iptables", follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))

    def test_firewall_export_failure_returns_500(self):
        from app import firewall

        with patch.object(firewall, "_run", return_value=(1, "", "permission denied")):
            resp = self.client.get("/api/firewall/export?type=iptables")

        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.get_json()["ok"])

    def test_firewall_import_iptables(self):
        from app import firewall
        import io

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch("app.firewall.subprocess.run", return_value=mock_result):
            resp = self.client.post(
                "/api/firewall/import",
                data={"type": "iptables",
                      "file": (io.BytesIO(b"*filter\nCOMMIT\n"), "iptables.rules")},
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_firewall_import_nftables(self):
        import io

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch("app.firewall._run", return_value=(0, "table ip filter {}\n", "")), \
             patch("app.firewall.subprocess.run", return_value=mock_result):
            resp = self.client.post(
                "/api/firewall/import",
                data={"type": "nftables",
                      "file": (io.BytesIO(b"table ip filter {}\n"), "nftables.rules")},
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_firewall_import_no_file(self):
        resp = self.client.post(
            "/api/firewall/import",
            data={"type": "iptables"},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

    def test_firewall_import_rejects_oversized_upload(self):
        """Uploads larger than MAX_CONTENT_LENGTH are rejected with 413."""
        import io

        original_limit = self.app.config["MAX_CONTENT_LENGTH"]
        self.app.config["MAX_CONTENT_LENGTH"] = 1024  # 1 KiB for this test
        try:
            oversized = b"x" * 2048
            resp = self.client.post(
                "/api/firewall/import",
                data={"type": "iptables", "file": (io.BytesIO(oversized), "big.rules")},
                content_type="multipart/form-data",
            )
            self.assertEqual(resp.status_code, 413)
        finally:
            self.app.config["MAX_CONTENT_LENGTH"] = original_limit

    def test_firewall_import_invalid_type(self):
        import io

        resp = self.client.post(
            "/api/firewall/import",
            data={"type": "both",
                  "file": (io.BytesIO(b"*filter\nCOMMIT\n"), "rules.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

    def test_firewall_import_requires_login(self):
        self.client.get("/logout")
        resp = self.client.post("/api/firewall/import", follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))


class TestWireguardExportImport(unittest.TestCase):
    """Tests for the WireGuard config export/import helper functions and API routes."""

    def setUp(self):
        _reset_user_store()
        from app import create_app
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self._login()

    def tearDown(self):
        _reset_user_store()

    def _login(self):
        self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
        )

    # ------------------------------------------------------------------
    # wireguard.py unit tests
    # ------------------------------------------------------------------

    def test_export_wg_configs_no_directory(self):
        from app import wireguard

        with patch.object(wireguard.os.path, "isdir", return_value=False):
            ok, configs, error = wireguard.export_wg_configs()

        self.assertFalse(ok)
        self.assertIn("not found", error)

    def test_export_wg_configs_no_conf_files(self):
        from app import wireguard

        with patch.object(wireguard.os.path, "isdir", return_value=True), \
             patch.object(wireguard.os, "listdir", return_value=["readme.txt"]):
            ok, configs, error = wireguard.export_wg_configs()

        self.assertFalse(ok)
        self.assertIn("No WireGuard config files found", error)

    def test_export_wg_configs_success(self):
        import tempfile
        import shutil
        from app import wireguard

        tmpdir = tempfile.mkdtemp()
        try:
            conf_content = "[Interface]\nPrivateKey = abc123\n"
            with open(os.path.join(tmpdir, "wg0.conf"), "w") as f:
                f.write(conf_content)

            orig_dir = wireguard._WG_CONFIG_DIR
            wireguard._WG_CONFIG_DIR = tmpdir
            try:
                ok, configs, error = wireguard.export_wg_configs()
            finally:
                wireguard._WG_CONFIG_DIR = orig_dir
        finally:
            shutil.rmtree(tmpdir)

        self.assertTrue(ok)
        self.assertIn("wg0.conf", configs)
        self.assertIn("PrivateKey", configs["wg0.conf"])

    def test_import_wg_config_invalid_filename(self):
        from app import wireguard

        result = wireguard.import_wg_config("../etc/passwd", "malicious")
        self.assertFalse(result["ok"])
        self.assertIn("Invalid config filename", result["error"])

    def test_import_wg_config_no_conf_extension(self):
        from app import wireguard

        result = wireguard.import_wg_config("wg0.sh", "content")
        self.assertFalse(result["ok"])

    def test_import_wg_config_success(self):
        import tempfile
        import shutil
        from app import wireguard

        tmpdir = tempfile.mkdtemp()
        orig_dir = wireguard._WG_CONFIG_DIR
        wireguard._WG_CONFIG_DIR = tmpdir
        try:
            result = wireguard.import_wg_config("wg0.conf", "[Interface]\nPrivateKey = xyz\n")
            self.assertTrue(result["ok"])
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "wg0.conf")))
            mode = oct(os.stat(os.path.join(tmpdir, "wg0.conf")).st_mode)
            self.assertTrue(mode.endswith("600"))
        finally:
            wireguard._WG_CONFIG_DIR = orig_dir
            shutil.rmtree(tmpdir)

    # ------------------------------------------------------------------
    # Route tests
    # ------------------------------------------------------------------

    def test_wireguard_export_single_config(self):
        import tempfile
        import shutil
        from app import wireguard

        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "wg0.conf"), "w") as f:
                f.write("[Interface]\nPrivateKey = abc\n")

            orig_dir = wireguard._WG_CONFIG_DIR
            wireguard._WG_CONFIG_DIR = tmpdir
            try:
                resp = self.client.get("/api/wireguard/export")
            finally:
                wireguard._WG_CONFIG_DIR = orig_dir
        finally:
            shutil.rmtree(tmpdir)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"[Interface]", resp.data)
        self.assertIn("wg0.conf", resp.headers.get("Content-Disposition", ""))

    def test_wireguard_export_multiple_configs_returns_zip(self):
        import tempfile
        import shutil
        import zipfile as zf
        from app import wireguard

        tmpdir = tempfile.mkdtemp()
        try:
            for name in ("wg0.conf", "wg1.conf"):
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write(f"[Interface]\n# {name}\n")

            orig_dir = wireguard._WG_CONFIG_DIR
            wireguard._WG_CONFIG_DIR = tmpdir
            try:
                resp = self.client.get("/api/wireguard/export")
            finally:
                wireguard._WG_CONFIG_DIR = orig_dir
        finally:
            shutil.rmtree(tmpdir)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "application/zip")
        import io
        with zf.ZipFile(io.BytesIO(resp.data)) as z:
            names = z.namelist()
        self.assertIn("wg0.conf", names)
        self.assertIn("wg1.conf", names)

    def test_wireguard_export_no_configs_returns_500(self):
        from app import wireguard

        with patch.object(wireguard.os.path, "isdir", return_value=False):
            resp = self.client.get("/api/wireguard/export")

        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.get_json()["ok"])

    def test_wireguard_export_requires_login(self):
        self.client.get("/logout")
        resp = self.client.get("/api/wireguard/export", follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))

    def test_wireguard_import_success(self):
        import tempfile
        import shutil
        import io
        from app import wireguard

        tmpdir = tempfile.mkdtemp()
        orig_dir = wireguard._WG_CONFIG_DIR
        wireguard._WG_CONFIG_DIR = tmpdir
        try:
            resp = self.client.post(
                "/api/wireguard/import",
                data={"file": (io.BytesIO(b"[Interface]\nPrivateKey = xyz\n"), "wg0.conf")},
                content_type="multipart/form-data",
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.get_json()["ok"])
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "wg0.conf")))
        finally:
            wireguard._WG_CONFIG_DIR = orig_dir
            shutil.rmtree(tmpdir)

    def test_wireguard_import_invalid_filename(self):
        import io

        resp = self.client.post(
            "/api/wireguard/import",
            data={"file": (io.BytesIO(b"content"), "../etc/passwd")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.get_json()["ok"])

    def test_wireguard_import_no_file(self):
        resp = self.client.post(
            "/api/wireguard/import",
            data={},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])


class TestLoginRateLimit(unittest.TestCase):
    """Failed login attempts from the same client should eventually be throttled."""

    def setUp(self):
        _reset_user_store()
        from app import create_app
        import app.auth as auth_mod

        # Reset any state left over from other tests / a previous run.
        auth_mod._login_attempts.clear()

        self.auth_mod = auth_mod
        self.app = create_app()
        self.app.testing = True
        self.app.config["LOGIN_RATE_LIMIT_ATTEMPTS"] = 3
        self.client = self.app.test_client()

    def tearDown(self):
        _reset_user_store()
        self.auth_mod._login_attempts.clear()

    def test_lockout_after_repeated_failures(self):
        for _ in range(3):
            resp = self.client.post(
                "/login",
                data={"username": "admin", "password": "wrong"},
            )
            self.assertEqual(resp.status_code, 200)

        # Fourth attempt (even with the correct password) should be blocked.
        resp = self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
        )
        self.assertEqual(resp.status_code, 429)

    def test_successful_login_clears_attempts(self):
        resp = self.client.post(
            "/login",
            data={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"WireGuard", resp.data)


class TestCsrfProtection(unittest.TestCase):
    """CSRF protection should be enforced when WTF_CSRF_ENABLED is on."""

    def setUp(self):
        _reset_user_store()
        from app import create_app
        self.app = create_app()
        self.app.testing = True
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        _reset_user_store()

    def test_login_without_token_rejected(self):
        resp = self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
        )
        # Non-API routes get a friendly redirect (with a flashed message)
        # instead of Flask-WTF's raw HTML error page.
        self.assertEqual(resp.status_code, 302)

    def test_login_with_token_succeeds(self):
        get_resp = self.client.get("/login")
        # Extract the CSRF token embedded as a hidden input.
        import re
        match = re.search(rb'name="csrf_token" value="([^"]+)"', get_resp.data)
        self.assertIsNotNone(match)
        token = match.group(1).decode()

        resp = self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass", "csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"WireGuard", resp.data)

    def test_api_restart_without_token_rejected(self):
        self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
            headers={"X-CSRFToken": self._get_token()},
        )
        resp = self.client.post("/api/restart")
        self.assertEqual(resp.status_code, 400)

    def test_api_csrf_failure_returns_json_not_html(self):
        """Regression test: a CSRF failure on an /api/ route must return a
        JSON body, not Flask-WTF's default HTML error page. Returning HTML
        there breaks every fetch()-based button on the site (Save current
        rules, Restart, rename peer, ...), which all call resp.json() and
        would otherwise crash with "Unexpected token '<' ... is not valid
        JSON" in the browser console instead of showing a readable error.
        """
        self.client.post(
            "/login",
            data={"username": "admin", "password": "testpass"},
            headers={"X-CSRFToken": self._get_token()},
        )
        resp = self.client.post("/api/firewall/save", json={"type": "iptables"})
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.content_type.startswith("application/json"))
        body = resp.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("error", body)

    def _get_token(self):
        import re
        get_resp = self.client.get("/login")
        match = re.search(rb'name="csrf_token" value="([^"]+)"', get_resp.data)
        return match.group(1).decode()


class TestUserStoreStartupMessages(unittest.TestCase):
    """UserStore should clearly log whether ADMIN_USERNAME/ADMIN_PASSWORD were
    actually applied, since they're silently ignored once the users file
    already exists -- this is the #1 cause of "my credentials don't work"
    reports, so the behavior is covered explicitly here."""

    def setUp(self):
        _reset_user_store()

    def tearDown(self):
        _reset_user_store()

    def test_seeding_a_fresh_store_prints_confirmation(self):
        import io
        import contextlib
        from app.auth import UserStore

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            UserStore("/tmp/test_users_wireguard.json")

        output = buf.getvalue()
        self.assertIn("created initial admin account", output)
        self.assertIn("admin", output)

    def test_loading_an_existing_store_warns_env_vars_are_ignored(self):
        import io
        import contextlib
        from app.auth import UserStore

        # First run: seeds the file.
        UserStore("/tmp/test_users_wireguard.json")

        # Second run (simulating a restart after changing ADMIN_PASSWORD):
        # the existing file wins, and this must be made obvious in the logs.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            UserStore("/tmp/test_users_wireguard.json")

        output = buf.getvalue()
        self.assertIn("ignored while this file exists", output)


if __name__ == "__main__":
    unittest.main()
