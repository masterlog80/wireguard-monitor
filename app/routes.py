"""Main routes blueprint."""
from __future__ import annotations

import io
import os
import re
import subprocess
import zipfile

from flask import Blueprint, jsonify, make_response, render_template, request, send_file
from flask_login import login_required

from . import wireguard, firewall
from .peer_names import get_peer_name_store

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html")


@main_bp.route("/firewall")
@login_required
def firewall_page():
    rules = firewall.get_firewall_rules()
    return render_template("firewall.html", rules=rules)


# ---------------------------------------------------------------------------
# JSON API endpoints (polled by the dashboard JS every 5 s)
# ---------------------------------------------------------------------------


@main_bp.route("/api/status")
@login_required
def api_status():
    return jsonify(wireguard.get_wg_status())


@main_bp.route("/api/peers")
@login_required
def api_peers():
    return jsonify(wireguard.get_peers())


@main_bp.route("/api/throughput")
@login_required
def api_throughput():
    return jsonify(wireguard.get_throughput_history())


@main_bp.route("/api/ping")
@login_required
def api_ping():
    return jsonify(wireguard.get_ping_history())


@main_bp.route("/api/restart", methods=["POST"])
@login_required
def api_restart():
    """Restart the WireGuard service for each active interface."""
    interfaces = wireguard.get_interfaces()
    if not interfaces:
        return jsonify({"ok": False, "error": "No WireGuard interfaces found."}), 400

    errors = []
    for iface in interfaces:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", iface):
            errors.append(f"Invalid interface name: {iface!r}")
            continue
        try:
            result = subprocess.run(
                ["systemctl", "restart", f"wg-quick@{iface}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                errors.append(f"{iface}: {result.stderr.strip() or 'restart failed'}")
        except FileNotFoundError:
            errors.append(f"{iface}: systemctl not found")
        except subprocess.TimeoutExpired:
            errors.append(f"{iface}: restart timed out")

    if errors:
        return jsonify({"ok": False, "error": "; ".join(errors)}), 500
    return jsonify({"ok": True, "restarted": interfaces})


# ---------------------------------------------------------------------------
# Peer name aliases
# ---------------------------------------------------------------------------


@main_bp.route("/api/peer_names", methods=["GET"])
@login_required
def api_peer_names():
    """Return all peer name aliases as a mapping of public_key -> name."""
    return jsonify(get_peer_name_store().get_all())


@main_bp.route("/api/peer_names/<path:public_key>", methods=["POST"])
@login_required
def api_set_peer_name(public_key):
    """Set or update the display name for a peer."""
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "Name cannot be empty"}), 400
    if len(name) > 64:
        return jsonify({"ok": False, "error": "Name too long (max 64 characters)"}), 400
    get_peer_name_store().set(public_key, name)
    return jsonify({"ok": True})


@main_bp.route("/api/peer_names/<path:public_key>", methods=["DELETE"])
@login_required
def api_delete_peer_name(public_key):
    """Remove the display name for a peer (reverts to showing the public key)."""
    get_peer_name_store().delete(public_key)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Firewall save / restore API
# ---------------------------------------------------------------------------


@main_bp.route("/api/firewall/saved_info")
@login_required
def api_firewall_saved_info():
    """Return metadata about any saved firewall rule snapshots."""
    return jsonify(firewall.get_saved_rules_info())


@main_bp.route("/api/firewall/save", methods=["POST"])
@login_required
def api_firewall_save():
    """Save the current firewall rules.

    Accepts an optional JSON body ``{"type": "iptables"|"nftables"|"both"}``.
    Defaults to ``"both"`` when type is omitted.
    """
    data = request.get_json(silent=True) or {}
    rule_type = str(data.get("type", "both")).lower()
    if rule_type not in ("iptables", "nftables", "both"):
        return jsonify({"ok": False, "error": "type must be 'iptables', 'nftables', or 'both'"}), 400

    results: dict = {}
    if rule_type in ("iptables", "both"):
        results["iptables"] = firewall.save_iptables_rules()
    if rule_type in ("nftables", "both"):
        results["nftables"] = firewall.save_nftables_rules()

    overall_ok = bool(results) and all(v.get("ok") for v in results.values())
    status_code = 200 if overall_ok else 500
    return jsonify({"ok": overall_ok, "results": results}), status_code


@main_bp.route("/api/firewall/restore", methods=["POST"])
@login_required
def api_firewall_restore():
    """Restore previously saved firewall rules.

    Accepts an optional JSON body ``{"type": "iptables"|"nftables"|"both"}``.
    Defaults to ``"both"`` when type is omitted.
    """
    data = request.get_json(silent=True) or {}
    rule_type = str(data.get("type", "both")).lower()
    if rule_type not in ("iptables", "nftables", "both"):
        return jsonify({"ok": False, "error": "type must be 'iptables', 'nftables', or 'both'"}), 400

    results: dict = {}
    if rule_type in ("iptables", "both"):
        results["iptables"] = firewall.restore_iptables_rules()
    if rule_type in ("nftables", "both"):
        results["nftables"] = firewall.restore_nftables_rules()

    overall_ok = bool(results) and all(v.get("ok") for v in results.values())
    status_code = 200 if overall_ok else 500
    return jsonify({"ok": overall_ok, "results": results}), status_code


# ---------------------------------------------------------------------------
# Firewall export / import API
# ---------------------------------------------------------------------------


@main_bp.route("/api/firewall/export")
@login_required
def api_firewall_export():
    """Export current firewall rules as a downloadable text file.

    Query parameter ``type`` selects which ruleset to export:
    ``iptables`` (default) or ``nftables``.
    """
    rule_type = request.args.get("type", "iptables").lower()
    if rule_type not in ("iptables", "nftables"):
        return jsonify({"ok": False, "error": "type must be 'iptables' or 'nftables'"}), 400

    if rule_type == "iptables":
        ok, content, error = firewall.export_iptables_rules()
        filename = "iptables.rules"
    else:
        ok, content, error = firewall.export_nftables_rules()
        filename = "nftables.rules"

    if not ok:
        return jsonify({"ok": False, "error": error}), 500

    response = make_response(content)
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response


@main_bp.route("/api/firewall/import", methods=["POST"])
@login_required
def api_firewall_import():
    """Import and immediately apply firewall rules from an uploaded file.

    Expects a multipart form with:
    - ``file``: the rules file
    - ``type``: ``"iptables"`` or ``"nftables"``
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400
    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"ok": False, "error": "No filename provided"}), 400

    rule_type = request.form.get("type", "").lower()
    if rule_type not in ("iptables", "nftables"):
        return jsonify({"ok": False, "error": "type must be 'iptables' or 'nftables'"}), 400

    try:
        content = uploaded.read().decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return jsonify({"ok": False, "error": "Could not read uploaded file"}), 400

    if rule_type == "iptables":
        result = firewall.import_iptables_rules(content)
    else:
        result = firewall.import_nftables_rules(content)

    status_code = 200 if result["ok"] else 500
    return jsonify(result), status_code


# ---------------------------------------------------------------------------
# WireGuard config export / import API
# ---------------------------------------------------------------------------


@main_bp.route("/api/wireguard/export")
@login_required
def api_wireguard_export():
    """Export WireGuard config file(s) as a download.

    If a single ``.conf`` file is found it is returned as plain text.
    If multiple files are found they are bundled in a ZIP archive.
    """
    ok, configs, error = wireguard.export_wg_configs()
    if not ok:
        return jsonify({"ok": False, "error": error}), 500

    if len(configs) == 1:
        fname, content = next(iter(configs.items()))
        response = make_response(content)
        response.headers["Content-Disposition"] = f'attachment; filename="{fname}"'
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        return response

    # Multiple configs: bundle as a ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in configs.items():
            zf.writestr(fname, content)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="wireguard-configs.zip",
    )


@main_bp.route("/api/wireguard/import", methods=["POST"])
@login_required
def api_wireguard_import():
    """Import a WireGuard config file and save it to the config directory.

    Expects a multipart form with a ``file`` field containing a ``.conf`` file.
    The original filename is used as the destination name.
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400
    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"ok": False, "error": "No filename provided"}), 400

    filename = os.path.basename(uploaded.filename)
    try:
        content = uploaded.read().decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return jsonify({"ok": False, "error": "Could not read uploaded file"}), 400

    result = wireguard.import_wg_config(filename, content)
    status_code = 200 if result["ok"] else 500
    return jsonify(result), status_code
