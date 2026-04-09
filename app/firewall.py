"""Firewall rules module – reads, saves, and restores iptables / nftables rules."""
from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from config import Config


def _run(cmd: List[str]) -> Tuple[int, str, str]:
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


def _ensure_save_dir() -> str:
    """Ensure the save directory exists and return its path."""
    save_dir = Config.FIREWALL_SAVE_DIR
    os.makedirs(save_dir, exist_ok=True)
    return save_dir


def _iptables_save_path() -> str:
    return os.path.join(_ensure_save_dir(), "iptables.rules")


def _nftables_save_path() -> str:
    return os.path.join(_ensure_save_dir(), "nftables.rules")


def get_iptables_rules() -> Dict[str, Any]:
    """Return iptables rules parsed into sections."""
    tables = ["filter", "nat", "mangle", "raw"]
    result: Dict[str, Any] = {"available": False, "tables": {}}

    for table in tables:
        rc, out, err = _run(["iptables", "-t", table, "-L", "-n", "-v", "--line-numbers"])
        if rc == 0:
            result["available"] = True
            result["tables"][table] = _parse_iptables_output(out)
        else:
            result["tables"][table] = {"error": err.strip() or "Permission denied"}

    return result


def _parse_iptables_output(text: str) -> Dict[str, Any]:
    """Parse ``iptables -L -n -v --line-numbers`` output into chains."""
    chains: Dict[str, List[str]] = {}
    current_chain: str | None = None

    for line in text.splitlines():
        if line.startswith("Chain "):
            # e.g. "Chain INPUT (policy ACCEPT 1234 packets)"
            chain_name = line.split()[1]
            current_chain = chain_name
            chains[current_chain] = []
        elif current_chain is not None and line.strip():
            chains[current_chain].append(line)

    return {"chains": chains}


def get_nftables_rules() -> Dict[str, Any]:
    """Return nftables ruleset as plain text."""
    rc, out, err = _run(["nft", "list", "ruleset"])
    if rc == 0:
        return {"available": True, "ruleset": out}
    return {"available": False, "error": err.strip() or "nft not available"}


def get_firewall_rules() -> Dict[str, Any]:
    """Return combined firewall rules from iptables and nftables."""
    return {
        "iptables": get_iptables_rules(),
        "nftables": get_nftables_rules(),
    }


# ---------------------------------------------------------------------------
# Save / Restore
# ---------------------------------------------------------------------------


def save_iptables_rules() -> Dict[str, Any]:
    """Save current iptables rules to a file using ``iptables-save``."""
    rc, out, err = _run(["iptables-save"])
    if rc != 0:
        return {"ok": False, "error": err.strip() or "iptables-save failed"}
    path = _iptables_save_path()
    try:
        with open(path, "w") as f:
            f.write(out)
        saved_at = os.stat(path).st_mtime
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": path, "saved_at": saved_at}


def restore_iptables_rules() -> Dict[str, Any]:
    """Restore iptables rules from the previously saved file."""
    path = _iptables_save_path()
    if not os.path.exists(path):
        return {"ok": False, "error": "No saved iptables rules found"}
    try:
        with open(path) as f:
            rules_content = f.read()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        result = subprocess.run(
            ["iptables-restore"],
            input=rules_content,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "Command not found: iptables-restore"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out"}
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip() or "iptables-restore failed"}
    return {"ok": True}


def save_nftables_rules() -> Dict[str, Any]:
    """Save current nftables ruleset to a file using ``nft list ruleset``."""
    rc, out, err = _run(["nft", "list", "ruleset"])
    if rc != 0:
        return {"ok": False, "error": err.strip() or "nft not available"}
    path = _nftables_save_path()
    try:
        with open(path, "w") as f:
            f.write(out)
        saved_at = os.stat(path).st_mtime
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": path, "saved_at": saved_at}


def restore_nftables_rules() -> Dict[str, Any]:
    """Restore nftables rules from the previously saved file.

    The current ruleset is captured before flushing so it can be reloaded if
    applying the saved rules fails, avoiding a window with no firewall rules.
    """
    path = _nftables_save_path()
    if not os.path.exists(path):
        return {"ok": False, "error": "No saved nftables rules found"}

    # Capture the current ruleset so we can roll back if restore fails.
    rc_backup, current_rules, _ = _run(["nft", "list", "ruleset"])

    rc_flush, _, err_flush = _run(["nft", "flush", "ruleset"])
    if rc_flush != 0:
        return {"ok": False, "error": err_flush.strip() or "nft flush ruleset failed"}

    rc, _, err = _run(["nft", "-f", path])
    if rc != 0:
        # Attempt to roll back to the pre-flush ruleset.
        if rc_backup == 0 and current_rules:
            try:
                result = subprocess.run(
                    ["nft", "-f", "/dev/stdin"],
                    input=current_rules,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                rollback_note = (
                    " (previous ruleset restored)"
                    if result.returncode == 0
                    else " (rollback also failed)"
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                rollback_note = " (rollback also failed)"
        else:
            rollback_note = ""
        return {"ok": False, "error": (err.strip() or "nft -f failed") + rollback_note}

    return {"ok": True}


def get_saved_rules_info() -> Dict[str, Any]:
    """Return metadata about any previously saved rule snapshots."""

    def _file_info(path: str) -> Optional[Dict[str, Any]]:
        if os.path.exists(path):
            try:
                stat = os.stat(path)
                return {"exists": True, "saved_at": stat.st_mtime, "size": stat.st_size}
            except OSError:
                pass
        return {"exists": False}

    return {
        "iptables": _file_info(_iptables_save_path()),
        "nftables": _file_info(_nftables_save_path()),
    }
