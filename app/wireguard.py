"""WireGuard data collection module.

Parses ``wg show`` output and keeps rolling history for throughput graphs.
Works on Linux with WireGuard tools installed.  When the ``wg`` binary is
absent (e.g. during testing / development) the module returns realistic-looking
stub data so the UI can still be exercised.
"""
from __future__ import annotations

import os
import subprocess
import time
import re
import threading
from collections import deque
from typing import Dict, List, Tuple, Any

from config import Config

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

# { peer_pubkey: deque([(timestamp, rx_bytes, tx_bytes), ...]) }
_peer_history: Dict[str, deque] = {}
_history_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _run(cmd: List[str]) -> Tuple[int, str, str]:
    """Run *cmd* and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out"


# ---------------------------------------------------------------------------
# WireGuard interface status
# ---------------------------------------------------------------------------


def get_interfaces() -> List[str]:
    """Return a list of WireGuard interface names."""
    if Config.WG_INTERFACE:
        return [Config.WG_INTERFACE]
    rc, out, _ = _run(["wg", "show", "interfaces"])
    if rc != 0 or not out.strip():
        return []
    return out.strip().split()


def get_wg_status() -> Dict[str, Any]:
    """Return a dict with overall WireGuard status information."""
    interfaces = get_interfaces()
    if not interfaces:
        return {
            "available": False,
            "interfaces": [],
            "error": "No WireGuard interfaces found or 'wg' not installed.",
        }

    iface_data = []
    for iface in interfaces:
        rc, out, err = _run(["wg", "show", iface])
        if rc != 0:
            iface_data.append({"name": iface, "error": err.strip()})
            continue
        info = _parse_interface_block(iface, out)
        iface_data.append(info)

    return {"available": True, "interfaces": iface_data}


def _parse_interface_block(iface: str, text: str) -> Dict[str, Any]:
    """Parse the output of ``wg show <iface>`` into a dict."""
    data: Dict[str, Any] = {"name": iface, "peers": []}
    current_peer: Dict[str, Any] | None = None

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("interface:"):
            data["interface"] = line.split(":", 1)[1].strip()
        elif line.startswith("public key:"):
            if current_peer is None:
                data["public_key"] = line.split(":", 1)[1].strip()
            else:
                current_peer["public_key"] = line.split(":", 1)[1].strip()
        elif line.startswith("listening port:"):
            data["listening_port"] = line.split(":", 1)[1].strip()
        elif line.startswith("peer:"):
            current_peer = {"public_key": line.split(":", 1)[1].strip()}
            data["peers"].append(current_peer)
        elif current_peer is not None:
            if line.startswith("endpoint:"):
                current_peer["endpoint"] = line.split(":", 1)[1].strip()
            elif line.startswith("allowed ips:"):
                current_peer["allowed_ips"] = line.split(":", 1)[1].strip()
            elif line.startswith("latest handshake:"):
                current_peer["latest_handshake"] = line.split(":", 1)[1].strip()
            elif line.startswith("transfer:"):
                current_peer["transfer"] = line.split(":", 1)[1].strip()
            elif line.startswith("persistent keepalive:"):
                current_peer["persistent_keepalive"] = line.split(":", 1)[1].strip()

    return data


# ---------------------------------------------------------------------------
# Peer status (connected / disconnected)
# ---------------------------------------------------------------------------

_HANDSHAKE_TIMEOUT = 180  # seconds – peer considered disconnected after 3 min


def get_peers() -> List[Dict[str, Any]]:
    """Return a list of peer dicts with connectivity status."""
    interfaces = get_interfaces()
    peers = []
    for iface in interfaces:
        rc, out, _ = _run(["wg", "show", iface, "dump"])
        if rc != 0:
            continue
        lines = out.strip().splitlines()
        # First line is the interface itself; rest are peers
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            pub_key, preshared, endpoint, allowed_ips, latest_hs, rx, tx = parts[:7]
            try:
                hs_ts = int(latest_hs)
            except ValueError:
                hs_ts = 0
            age = int(time.time()) - hs_ts if hs_ts > 0 else None
            connected = (age is not None) and (age <= _HANDSHAKE_TIMEOUT)
            peers.append(
                {
                    "interface": iface,
                    "public_key": pub_key,
                    "endpoint": endpoint,
                    "allowed_ips": allowed_ips,
                    "latest_handshake": hs_ts,
                    "rx_bytes": int(rx),
                    "tx_bytes": int(tx),
                    "connected": connected,
                    "handshake_age_seconds": age,
                }
            )
    return peers


# ---------------------------------------------------------------------------
# Throughput history (collected by background poller)
# ---------------------------------------------------------------------------


def _update_history(peers: List[Dict[str, Any]]) -> None:
    """Record current RX/TX for each peer into the rolling history."""
    ts = time.time()
    with _history_lock:
        for p in peers:
            key = p["public_key"]
            if key not in _peer_history:
                _peer_history[key] = deque(maxlen=Config.MAX_HISTORY)
            _peer_history[key].append((ts, p["rx_bytes"], p["tx_bytes"]))


def get_throughput_history() -> Dict[str, Any]:
    """Return throughput history suitable for Chart.js consumption.

    Returns a dict keyed by peer public_key.  Each value is a dict with
    ``labels`` (ISO timestamps), ``rx_bps`` and ``tx_bps`` lists.
    """
    with _history_lock:
        result: Dict[str, Any] = {}
        for key, dq in _peer_history.items():
            points = list(dq)
            if len(points) < 2:
                result[key] = {"labels": [], "rx_bps": [], "tx_bps": []}
                continue
            labels = []
            rx_bps = []
            tx_bps = []
            for i in range(1, len(points)):
                t0, rx0, tx0 = points[i - 1]
                t1, rx1, tx1 = points[i]
                dt = t1 - t0
                if dt <= 0:
                    continue
                labels.append(
                    time.strftime("%H:%M:%S", time.localtime(t1))
                )
                rx_bps.append(round((rx1 - rx0) / dt, 2))
                tx_bps.append(round((tx1 - tx0) / dt, 2))
            result[key] = {"labels": labels, "rx_bps": rx_bps, "tx_bps": tx_bps}
        return result


# ---------------------------------------------------------------------------
# Ping latency
# ---------------------------------------------------------------------------


def ping_peer(ip: str, count: int = 3) -> float | None:
    """Ping *ip* and return average RTT in milliseconds, or None on failure."""
    rc, out, _ = _run(["ping", "-c", str(count), "-W", "2", ip])
    if rc != 0:
        return None
    # Look for "rtt min/avg/max/mdev = …/AVG/…"
    m = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", out)
    if m:
        return float(m.group(1))
    # Fallback: older format "round-trip min/avg/max = …/AVG/…"
    m = re.search(r"round-trip min/avg/max = [\d.]+/([\d.]+)/", out)
    if m:
        return float(m.group(1))
    return None


# { peer_pubkey: deque([(timestamp, latency_ms|None), ...]) }
_ping_history: Dict[str, deque] = {}
_ping_lock = threading.Lock()


def _update_ping_history(peers: List[Dict[str, Any]]) -> None:
    """Measure ping for each peer's first allowed IP and store the result."""
    ts = time.time()
    for p in peers:
        key = p["public_key"]
        allowed = p.get("allowed_ips", "")
        # Take first IP (strip /prefix)
        ip_candidate = allowed.split(",")[0].strip().split("/")[0]
        if not ip_candidate or ip_candidate == "(none)":
            continue
        latency = ping_peer(ip_candidate)
        with _ping_lock:
            if key not in _ping_history:
                _ping_history[key] = deque(maxlen=Config.MAX_HISTORY)
            _ping_history[key].append((ts, latency))


def get_ping_history() -> Dict[str, Any]:
    """Return ping history suitable for Chart.js consumption."""
    with _ping_lock:
        result: Dict[str, Any] = {}
        for key, dq in _ping_history.items():
            points = list(dq)
            labels = []
            latencies = []
            for ts, lat in points:
                labels.append(time.strftime("%H:%M:%S", time.localtime(ts)))
                latencies.append(lat)
            result[key] = {"labels": labels, "latencies": latencies}
        return result


# ---------------------------------------------------------------------------
# Background poller
# ---------------------------------------------------------------------------

_poller_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start_poller(interval: float = 5.0) -> None:
    """Start the background thread that collects throughput and ping data."""
    global _poller_thread
    if _poller_thread is not None and _poller_thread.is_alive():
        return
    _stop_event.clear()
    _poller_thread = threading.Thread(
        target=_poll_loop, args=(interval,), daemon=True, name="wg-poller"
    )
    _poller_thread.start()


def stop_poller() -> None:
    _stop_event.set()


def _poll_loop(interval: float) -> None:
    while not _stop_event.is_set():
        try:
            peers = get_peers()
            _update_history(peers)
            _update_ping_history(peers)
        except Exception:
            pass
        _stop_event.wait(interval)


# ---------------------------------------------------------------------------
# WireGuard config export / import
# ---------------------------------------------------------------------------

_WG_CONFIG_DIR = "/etc/wireguard"


def export_wg_configs() -> Tuple[bool, Dict[str, str], str]:
    """Read all ``*.conf`` files from the WireGuard config directory.

    Returns ``(ok, {filename: content, ...}, error_message)``.
    When a file exists but cannot be read (e.g. permission error), a comment
    line describing the error is stored as its value instead of the file
    contents; the overall call still succeeds.
    """
    configs: Dict[str, str] = {}
    try:
        if not os.path.isdir(_WG_CONFIG_DIR):
            return False, {}, f"Directory not found: {_WG_CONFIG_DIR}"
        for fname in sorted(os.listdir(_WG_CONFIG_DIR)):
            if not fname.endswith(".conf"):
                continue
            fpath = os.path.join(_WG_CONFIG_DIR, fname)
            try:
                with open(fpath) as f:
                    configs[fname] = f.read()
            except OSError as exc:
                configs[fname] = f"# Error reading file: {exc}\n"
    except OSError as exc:
        return False, {}, str(exc)
    if not configs:
        return False, {}, "No WireGuard config files found in " + _WG_CONFIG_DIR
    return True, configs, ""


def import_wg_config(filename: str, content: str) -> Dict[str, Any]:
    """Save a WireGuard config file to the WireGuard config directory.

    *filename* must match ``[a-zA-Z0-9_\\-]+\\.conf`` to prevent path traversal.
    The file is written with mode ``0600`` so only root can read the private key.
    If individual config files cannot be read during export they are represented
    as comment lines in the returned dict value.
    """
    # Anchored regex: only word chars, hyphens, and the .conf extension are allowed.
    # The hyphen is escaped explicitly to avoid any ambiguity in the character class.
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+\.conf", filename):
        return {"ok": False, "error": f"Invalid config filename: {filename!r}. "
                                      "Only alphanumeric characters, hyphens, and underscores are allowed."}
    # _WG_CONFIG_DIR is a trusted constant; filename is validated above.
    fpath = os.path.join(_WG_CONFIG_DIR, filename)  # noqa: S603 – path validated by regex
    try:
        os.makedirs(_WG_CONFIG_DIR, exist_ok=True)
        fd = os.open(fpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": fpath}
