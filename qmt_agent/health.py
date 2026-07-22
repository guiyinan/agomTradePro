"""Local preflight probe for QMT Agent installation."""

from __future__ import annotations

import importlib.util
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .qmt_adapter import BrokerAdapter


def run_preflight(config: AgentConfig) -> dict[str, Any]:
    """Return an installation compatibility report without submitting orders."""

    checks = {
        "windows": platform.system() == "Windows",
        "python_version": sys.version.split()[0],
        "python_supported": sys.version_info >= (3, 10),
        "xtquant_installed": importlib.util.find_spec("xtquant") is not None,
        "qmt_client_version_recorded": _version_recorded(config.qmt_client_version),
        "xtquant_version_recorded": _version_recorded(config.xtquant_version),
        "qmt_userdata_exists": config.qmt_userdata_path.exists(),
        "state_parent_writable": _writable(config.state_dir),
        "log_parent_writable": _writable(config.log_dir),
        "https_server": config.server_url.startswith("https://"),
        "dry_run": config.dry_run,
    }
    checks["ready"] = all(
        bool(checks[key])
        for key in (
            "windows",
            "python_supported",
            "xtquant_installed",
            "qmt_client_version_recorded",
            "xtquant_version_recorded",
            "qmt_userdata_exists",
            "state_parent_writable",
            "log_parent_writable",
        )
    )
    return checks


def run_qmt_read_probe(
    config: AgentConfig,
    broker: BrokerAdapter,
    *,
    adapter_name: str = "xtquant",
) -> dict[str, Any]:
    """Probe QMT connectivity and read APIs without submitting or canceling orders."""

    report: dict[str, Any] = {
        "probe_contract": "agom-qmt-read-probe.v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "agent_id": config.agent_id,
        "system_account_id": config.system_account_id,
        "account_type": config.broker_account_type,
        "adapter": adapter_name,
        "external_evidence": adapter_name == "xtquant",
        "declared_versions": {
            "qmt_client": config.qmt_client_version,
            "xtquant": config.xtquant_version,
        },
        "read_only": True,
        "submitted_order": False,
        "canceled_order": False,
        "checks": {},
        "ready": False,
    }
    try:
        broker.connect()
        health = broker.health()
        snapshot = broker.account_snapshot()
        positions = snapshot.get("positions")
        orders = snapshot.get("orders")
        trades = snapshot.get("trades")
        checks = {
            "qmt_connected": bool(health.get("qmt_connected")),
            "qmt_version": str(health.get("qmt_version") or "unknown")[:128],
            "asset_query": all(
                key in snapshot for key in ("cash_available", "total_asset")
            ),
            "positions_query": isinstance(positions, list),
            "orders_query": isinstance(orders, list),
            "trades_query": isinstance(trades, list),
            "position_count": len(positions) if isinstance(positions, list) else -1,
            "order_count": len(orders) if isinstance(orders, list) else -1,
            "trade_count": len(trades) if isinstance(trades, list) else -1,
            "qmt_client_version_recorded": _version_recorded(
                config.qmt_client_version
            ),
            "xtquant_version_recorded": _version_recorded(config.xtquant_version),
        }
        report["checks"] = checks
        required_checks = [
            "qmt_connected",
            "asset_query",
            "positions_query",
            "orders_query",
            "trades_query",
        ]
        if adapter_name == "xtquant":
            required_checks.extend(
                ["qmt_client_version_recorded", "xtquant_version_recorded"]
            )
        report["ready"] = all(
            bool(checks[key])
            for key in required_checks
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        report["checks"] = {
            "qmt_connected": False,
            "failure_type": type(exc).__name__,
            "failure_code": _probe_failure_code(exc, config.qmt_userdata_path),
        }
    return report


def _probe_failure_code(exc: Exception, qmt_userdata_path: Path) -> str:
    """Return a stable, secret-free failure stage for operator diagnostics."""

    message = str(exc)
    if isinstance(exc, ImportError):
        return "XTQUANT_IMPORT_FAILED"
    if message == "QMT trader connection failed":
        if _qmt_server_start_denied(qmt_userdata_path):
            return "QMT_SERVER_NOT_ALLOWED"
        return "QMT_CONNECTION_FAILED"
    if message == "QMT account subscription failed":
        return "QMT_ACCOUNT_SUBSCRIPTION_FAILED"
    if isinstance(exc, OSError):
        return "QMT_IO_FAILED"
    return "BROKER_READ_FAILED"


def _qmt_server_start_denied(qmt_userdata_path: Path) -> bool:
    """Detect the vendor's explicit XtQuantServer authorization denial safely."""

    log_dir = qmt_userdata_path / "log"
    if not log_dir.is_dir():
        return False
    try:
        candidates = sorted(
            (
                path
                for pattern in ("XtClient_*.log", "XtMiniQmt_*.log")
                for path in log_dir.glob(pattern)
                if path.is_file()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:3]
        marker = b"The XtQuantServer is not allowed to start."
        for path in candidates:
            with path.open("rb") as handle:
                size = path.stat().st_size
                handle.seek(max(0, size - 1024 * 1024))
                if marker in handle.read():
                    return True
    except OSError:
        return False
    return False


def _version_recorded(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return bool(normalized and "replace-with" not in normalized and normalized != "unknown")


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".agom-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False
