"""
Data Center — Infrastructure Layer Connection Tester

Runtime connectivity probes for all configured data providers.
Migrated from apps.macro.infrastructure.datasource_connection_tester and
extended to support the full provider type set (tushare, akshare, qmt,
eastmoney, fred, wind, choice).
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from apps.data_center.domain.entities import ConnectionTestResult, ProviderConfig
from apps.data_center.infrastructure.macro_sources import AKShareAdapter, TushareAdapter

logger = logging.getLogger(__name__)

_TEST_TIMEOUT_SECONDS = 15
ConnectionProbe = Callable[[ProviderConfig, list[str]], ConnectionTestResult]


@dataclass(frozen=True)
class _ProbeOutcome:
    """Typed cross-thread probe result that does not expose exception messages."""

    result: ConnectionTestResult | None = None
    error_type: str = ""


def _log(logs: list[str], message: str) -> None:
    logs.append(message)


# ---------------------------------------------------------------------------
# Per-source probe functions
# ---------------------------------------------------------------------------


def _probe_tushare(config: ProviderConfig, logs: list[str]) -> ConnectionTestResult:
    """Test Tushare via a SHIBOR fetch (real parse path, not just HTTP ping)."""
    token = (config.api_key or "").strip()
    http_url = (config.http_url or "").strip() or None

    if not token:
        _log(logs, "[ERROR] Tushare Token not configured.")
        return ConnectionTestResult(
            success=False,
            status="error",
            summary="Tushare Token missing",
            logs=logs,
        )

    _log(logs, "[INFO] Initialising Tushare client.")
    if http_url:
        _log(logs, f"[INFO] Custom HTTP URL: {http_url}")

    adapter = TushareAdapter(token=token, http_url=http_url)
    end = date.today()
    start = end - timedelta(days=7)
    _log(logs, f"[INFO] SHIBOR probe window: {start} → {end}")

    data = adapter.fetch("SHIBOR", start, end)
    _log(logs, f"[SUCCESS] Tushare SHIBOR returned {len(data)} rows.")
    return ConnectionTestResult(
        success=True,
        status="success",
        summary=f"Tushare OK — SHIBOR probe returned {len(data)} rows",
        logs=logs,
    )


def _probe_akshare(config: ProviderConfig, logs: list[str]) -> ConnectionTestResult:
    """Test AKShare via a CN_PMI fetch."""
    _log(logs, "[INFO] AKShare is a public source — no token required.")
    adapter = AKShareAdapter()
    end = date.today()
    start = end - timedelta(days=400)
    _log(logs, f"[INFO] CN_PMI probe window: {start} → {end}")
    data = adapter.fetch("CN_PMI", start, end)
    _log(logs, f"[SUCCESS] AKShare CN_PMI returned {len(data)} rows.")
    return ConnectionTestResult(
        success=True,
        status="success",
        summary=f"AKShare OK — PMI probe returned {len(data)} rows",
        logs=logs,
    )


def _probe_qmt(config: ProviderConfig, logs: list[str]) -> ConnectionTestResult:
    """Test QMT local terminal connectivity."""
    from apps.data_center.infrastructure.gateways.qmt_gateway import QMTGateway

    extra = config.extra_config or {}
    _log(logs, "[INFO] Initialising QMT / XtQuant gateway.")
    if extra.get("client_path"):
        _log(logs, f"[INFO] client_path={extra['client_path']}")
    if extra.get("data_dir"):
        _log(logs, f"[INFO] data_dir={extra['data_dir']}")

    gateway = QMTGateway(source_name=config.name, extra_config=extra)
    gateway._load_xtdata()
    _log(logs, "[SUCCESS] QMT local terminal connected.")
    return ConnectionTestResult(
        success=True,
        status="success",
        summary="QMT local terminal OK",
        logs=logs,
    )


def _probe_eastmoney(config: ProviderConfig, logs: list[str]) -> ConnectionTestResult:
    """Test EastMoney via AKShareEastMoneyGateway (public source — no API key needed).

    Uses get_quote_snapshots() which is the real dispatch path for REALTIME_QUOTE.
    Returns success=True even when the market is closed (empty list is not a probe
    failure — it just means no current price).
    """
    from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
        AKShareEastMoneyGateway,
    )

    _log(logs, "[INFO] EastMoney is a public source — no API key required.")
    _log(logs, "[INFO] Initialising AKShareEastMoneyGateway for probe.")
    gateway = AKShareEastMoneyGateway()
    probe_codes = ["000001.SH"]
    _log(logs, f"[INFO] Fetching realtime quote for {probe_codes[0]}.")
    # get_quote_snapshots returns [] when market is closed or on transient errors
    snapshots = gateway.get_quote_snapshots(probe_codes)
    if not snapshots:
        _log(
            logs,
            "[WARN] Quote returned empty list — market may be closed or outside trading hours.",
        )
        return ConnectionTestResult(
            success=True,
            status="warning",
            summary="EastMoney gateway reachable; quote empty (market may be closed)",
            logs=logs,
        )
    price = snapshots[0].price
    _log(logs, f"[SUCCESS] EastMoney quote received: {probe_codes[0]} price={price}.")
    return ConnectionTestResult(
        success=True,
        status="success",
        summary=f"EastMoney OK — {probe_codes[0]} price={price}",
        logs=logs,
    )


def _probe_credential_only(config: ProviderConfig, logs: list[str]) -> ConnectionTestResult:
    """Validate that credentials are present for sources without a live probe."""
    api_key = (config.api_key or "").strip()
    if not api_key:
        _log(logs, "[ERROR] API key / token is missing.")
        return ConnectionTestResult(
            success=False,
            status="error",
            summary="Missing API key — cannot test connection",
            logs=logs,
        )
    _log(logs, "[WARN] Live probe not yet implemented for this source type.")
    _log(logs, "[INFO] API key is present; save config and monitor live status.")
    return ConnectionTestResult(
        success=False,
        status="warning",
        summary="Credentials validated, but live probe not yet implemented",
        logs=logs,
    )


# ---------------------------------------------------------------------------
# Timeout wrapper
# ---------------------------------------------------------------------------


def _run_with_timeout(
    config: ProviderConfig,
    logs: list[str],
    probe: ConnectionProbe,
    timeout: int = _TEST_TIMEOUT_SECONDS,
) -> ConnectionTestResult:
    result_q: queue.Queue[_ProbeOutcome] = queue.Queue(maxsize=1)
    probe_logs: list[str] = []

    def _worker() -> None:
        try:
            result_q.put(_ProbeOutcome(result=probe(config, probe_logs)))
        except Exception as exc:
            result_q.put(_ProbeOutcome(error_type=exc.__class__.__name__))

    thread = threading.Thread(
        target=_worker,
        name=f"dc-probe-{config.source_type}",
        daemon=True,
    )
    thread.start()

    try:
        outcome = result_q.get(timeout=timeout)
    except queue.Empty:
        logs.extend(probe_logs)
        _log(logs, f"[ERROR] Probe timed out after {timeout}s.")
        return ConnectionTestResult(
            success=False,
            status="error",
            summary=f"Connection test timed out (>{timeout}s)",
            logs=logs,
        )

    logs.extend(probe_logs)
    if outcome.result is None:
        error_type = outcome.error_type or "UnknownError"
        _log(logs, f"[ERROR] Probe raised: {error_type}")
        return ConnectionTestResult(
            success=False,
            status="error",
            summary=f"Connection test failed ({error_type})",
            logs=logs,
        )
    return outcome.result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_connection_test(config: ProviderConfig) -> ConnectionTestResult:
    """Dispatch a connectivity probe for *config* and return a structured result.

    The probe exercises the actual data-parse path (not just an HTTP ping) to
    avoid false-positives where connectivity succeeds but field parsing fails.
    """
    logs: list[str] = []
    _log(logs, f"[INFO] Testing provider: {config.name} ({config.source_type})")
    if not config.is_active:
        _log(logs, "[WARN] Provider is currently disabled — testing connectivity only.")

    try:
        if config.source_type == "tushare":
            return _run_with_timeout(config, logs, _probe_tushare)
        if config.source_type == "akshare":
            return _run_with_timeout(config, logs, _probe_akshare)
        if config.source_type == "qmt":
            return _run_with_timeout(config, logs, _probe_qmt)
        if config.source_type == "eastmoney":
            return _run_with_timeout(config, logs, _probe_eastmoney)
        if config.source_type in {"fred", "wind", "choice"}:
            return _probe_credential_only(config, logs)

        _log(logs, f"[ERROR] Unsupported source type: {config.source_type}")
        return ConnectionTestResult(
            success=False,
            status="error",
            summary=f"Unsupported source type: {config.source_type}",
            logs=logs,
        )
    except Exception as exc:
        error_type = exc.__class__.__name__
        _log(logs, f"[ERROR] Unexpected error: {error_type}")
        logger.error(
            "Unexpected error during connection test for %s (%s)",
            config.name,
            error_type,
        )
        return ConnectionTestResult(
            success=False,
            status="error",
            summary=f"Connection test failed ({error_type})",
            logs=logs,
        )
