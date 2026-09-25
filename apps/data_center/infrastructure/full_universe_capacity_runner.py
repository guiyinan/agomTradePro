"""Measured full-universe provider capacity evidence for release admission."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol, cast
from zoneinfo import ZoneInfo

from django.db import connection, connections, transaction

from apps.data_center.application.query_services import list_active_stock_codes_for_backfill
from apps.data_center.composition import get_provider_registry
from apps.data_center.domain.entities import QuoteSnapshot, ValuationFact
from apps.data_center.domain.protocols import (
    CurrentValuationBatchProviderProtocol,
    SessionQuoteBatchProviderProtocol,
)
from core.exceptions import DataFetchError

from .market_rehearsal_runner import (
    _SourceIdentity,
    canonical_publication_policy_evidence,
    market_rehearsal_source_digest,
    verify_candidate_release_image,
)
from .publication_policy_repository import PublicationPolicyRepository
from .rehearsal_http_capture import RehearsalHttpCapture, RehearsalHttpReceipt
from .rehearsal_identity import (
    RehearsalProviderIdentity,
    parse_rehearsal_identities,
    rehearsal_identities_digest,
    verify_configured_rehearsal_identities,
)


class _Sysconf(Protocol):
    """Portable typed boundary for Unix host memory queries."""

    def __call__(self, name: str) -> int: ...


class _RuntimeMonitor:
    """Sample PostgreSQL connections, lock waits and process RSS during one rehearsal."""

    def __init__(self, *, backend_pid: int, interval_seconds: float = 0.05) -> None:
        self.backend_pid = backend_pid
        self.interval_seconds = interval_seconds
        self.database_peak_connections = 0
        self.database_connection_limit = 0
        self.max_lock_wait_seconds = 0.0
        self.peak_memory_bytes = 0
        self.error_code = ""
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> _RuntimeMonitor:
        """Start sampling and require one successful database observation."""
        self._thread.start()
        if not self._ready.wait(timeout=5) or self.error_code:
            self._stop.set()
            self._thread.join(timeout=5)
            raise DataFetchError(
                "Capacity runtime monitor is unavailable",
                code="REHEARSAL_CAPACITY_MONITOR_UNAVAILABLE",
            )
        return self

    def __exit__(self, *_args: object) -> None:
        """Stop the monitor and fail later if sampling lost its evidence channel."""
        self._stop.set()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            self.error_code = "REHEARSAL_CAPACITY_MONITOR_TIMEOUT"

    def _run(self) -> None:
        lock_started: float | None = None
        try:
            while not self._stop.is_set():
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT count(*) FROM pg_stat_activity")
                    count = int(cursor.fetchone()[0])
                    cursor.execute("SHOW max_connections")
                    limit = int(cursor.fetchone()[0])
                    cursor.execute(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                        [self.backend_pid],
                    )
                    row = cursor.fetchone()
                self.database_peak_connections = max(self.database_peak_connections, count)
                self.database_connection_limit = limit
                self.peak_memory_bytes = max(self.peak_memory_bytes, _current_rss_bytes())
                now = time.monotonic()
                waiting = row is not None and row[0] == "Lock"
                if waiting and lock_started is None:
                    lock_started = now
                elif not waiting and lock_started is not None:
                    self.max_lock_wait_seconds = max(self.max_lock_wait_seconds, now - lock_started)
                    lock_started = None
                self._ready.set()
                self._stop.wait(self.interval_seconds)
            if lock_started is not None:
                self.max_lock_wait_seconds = max(
                    self.max_lock_wait_seconds, time.monotonic() - lock_started
                )
        except Exception:
            self.error_code = "REHEARSAL_CAPACITY_MONITOR_FAILED"
            self._ready.set()
        finally:
            connections["default"].close()


def _current_rss_bytes() -> int:
    """Return the process resident high-water mark from the Linux candidate runtime."""
    try:
        lines = Path("/proc/self/status").read_text(encoding="utf-8").splitlines()
        for field in ("VmHWM:", "VmRSS:"):
            for line in lines:
                if not line.startswith(field):
                    continue
                parts = line.split()
                if len(parts) == 3 and parts[2] == "kB":
                    return int(parts[1]) * 1024
    except (OSError, UnicodeError, ValueError):
        pass
    raise DataFetchError(
        "Process resident memory is unavailable",
        code="REHEARSAL_CAPACITY_MEMORY_UNAVAILABLE",
    )


def _memory_limit_bytes() -> int:
    """Read the effective cgroup or host memory limit used by the candidate process."""
    candidates = (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    )
    for path in candidates:
        try:
            value = path.read_text(encoding="ascii").strip()
            parsed = int(value) if value != "max" else 0
            # cgroup v1 represents "unlimited" with a near-int64 sentinel.
            if 0 < parsed < (1 << 60):
                return parsed
        except (OSError, UnicodeError, ValueError):
            continue
    sysconf = cast(_Sysconf | None, getattr(os, "sysconf", None))
    try:
        pages = sysconf("SC_PHYS_PAGES") if sysconf is not None else 0
        page_size = sysconf("SC_PAGE_SIZE") if sysconf is not None else 0
    except (OSError, ValueError):
        pages = page_size = 0
    if isinstance(pages, int) and isinstance(page_size, int) and min(pages, page_size) > 0:
        return pages * page_size
    raise DataFetchError(
        "Candidate memory limit is unavailable",
        code="REHEARSAL_CAPACITY_MEMORY_LIMIT_UNAVAILABLE",
    )


def _peak_requests(receipts: list[RehearsalHttpReceipt], window_seconds: float) -> int:
    """Return the greatest observed dispatch count in any sliding provider window."""
    instants = sorted(datetime.fromisoformat(item.started_at).timestamp() for item in receipts)
    peak = 0
    left = 0
    for right, instant in enumerate(instants):
        while instant - instants[left] >= window_seconds:
            left += 1
        peak = max(peak, right - left + 1)
    return peak


def _write_json(path: Path, payload: dict[str, object]) -> str:
    """Create one immutable canonical JSON artifact and return its SHA-256."""
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def _capacity_policy(source_root: Path) -> float:
    """Load the version-controlled minimum release margin from the candidate tree."""
    path = source_root / "governance" / "release_rehearsal_policy.json"
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("REHEARSAL_CAPACITY_POLICY_INVALID") from exc
    if not isinstance(payload, dict):
        raise ValueError("REHEARSAL_CAPACITY_POLICY_INVALID")
    margin = payload.get("minimum_capacity_margin_ratio")
    if (
        payload.get("schema") != "release.rehearsal-policy.v1"
        or isinstance(margin, bool)
        or not isinstance(margin, (int, float))
        or not math.isfinite(float(margin))
        or not 0 < float(margin) < 1
    ):
        raise ValueError("REHEARSAL_CAPACITY_POLICY_INVALID")
    return float(margin)


def _fact_coverage(
    facts: list[QuoteSnapshot] | list[ValuationFact],
    *,
    requested: tuple[str, ...],
    target_trade_date: date,
) -> dict[str, object]:
    """Validate returned identities and report target-session coverage without hiding gaps."""
    requested_set = set(requested)
    codes = [fact.asset_code for fact in facts]
    counts = Counter(codes)
    duplicate_codes = sorted(code for code, count in counts.items() if count > 1)
    extra_codes = sorted(set(codes) - requested_set)
    if duplicate_codes or extra_codes:
        raise DataFetchError(
            "Provider returned ambiguous full-universe identities",
            code="REHEARSAL_CAPACITY_PROVIDER_SCOPE_INVALID",
        )
    target_codes = {
        fact.asset_code
        for fact in facts
        if (
            fact.val_date == target_trade_date
            if isinstance(fact, ValuationFact)
            else fact.snapshot_at.astimezone(ZoneInfo("Asia/Shanghai")).date() == target_trade_date
        )
    }
    missing = sorted(requested_set - target_codes)
    return {
        "requested_count": len(requested),
        "returned_count": len(codes),
        "target_session_count": len(target_codes),
        "missing_target_session_count": len(missing),
        "missing_target_session_codes": missing,
        "extra_count": 0,
        "duplicate_count": 0,
    }


def collect_full_universe_capacity(
    *,
    quote_provider_id: int,
    valuation_provider_id: int,
    candidate_sha: str,
    target_trade_date: date,
    source_root: Path,
    output_dir: Path,
    provider_identities: tuple[RehearsalProviderIdentity, ...],
    provider_request_limit_per_window: int,
    provider_window_seconds: float,
    task_deadline_seconds: float,
    lock_wait_limit_seconds: float,
    max_dispatches: int = 20,
) -> dict[str, object]:
    """Exercise both providers for the exact full universe and persist measured capacity."""
    if connection.vendor != "postgresql" or connection.in_atomic_block:
        raise DataFetchError(
            "Capacity rehearsal requires a fresh PostgreSQL transaction",
            code="REHEARSAL_READ_ONLY_UNAVAILABLE",
        )
    if output_dir.exists():
        raise ValueError("REHEARSAL_CAPACITY_OUTPUT_EXISTS")
    if re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None:
        raise ValueError("REHEARSAL_CAPACITY_CANDIDATE_INVALID")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in (
            quote_provider_id,
            valuation_provider_id,
            provider_request_limit_per_window,
            max_dispatches,
        )
    ):
        raise ValueError("REHEARSAL_CAPACITY_INPUT_INVALID")
    numeric_limits = (
        provider_window_seconds,
        task_deadline_seconds,
        lock_wait_limit_seconds,
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
        for value in numeric_limits
    ):
        raise ValueError("REHEARSAL_CAPACITY_INPUT_INVALID")
    identities = parse_rehearsal_identities([asdict(item) for item in provider_identities])
    by_role = {item.role: item for item in identities}
    if (
        by_role["quote"].provider_id != quote_provider_id
        or by_role["valuation"].provider_id != valuation_provider_id
    ):
        raise ValueError("REHEARSAL_PROVIDER_IDENTITY_MISMATCH")
    verify_configured_rehearsal_identities(identities)

    started = datetime.now(UTC)
    minimum_capacity_margin = _capacity_policy(source_root)
    source_attestation, candidate_image_id = verify_candidate_release_image(
        source_root, candidate_sha
    )
    source_digest = market_rehearsal_source_digest(source_root)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", ["30000"])
            cursor.execute("SELECT pg_backend_pid()")
            backend_pid = int(cursor.fetchone()[0])
        registered_universe = tuple(sorted(set(list_active_stock_codes_for_backfill())))
        if not registered_universe:
            raise DataFetchError(
                "Capacity universe is empty", code="REHEARSAL_CAPACITY_UNIVERSE_EMPTY"
            )
        registry = get_provider_registry()
        valuation_policy = PublicationPolicyRepository().get_active("equity.valuation.fact")
        if valuation_policy is None:
            raise DataFetchError(
                "Valuation publication policy is unavailable",
                code="REHEARSAL_CAPACITY_POLICY_UNAVAILABLE",
            )
        valuation_policy_snapshot = canonical_publication_policy_evidence(valuation_policy)
        valuation_policy_sha256 = str(valuation_policy_snapshot["content_sha256"])
        quotes = registry.get_by_id(quote_provider_id)
        valuations = registry.get_by_id(valuation_provider_id)
        if not isinstance(quotes, SessionQuoteBatchProviderProtocol) or not isinstance(
            valuations, CurrentValuationBatchProviderProtocol
        ):
            raise DataFetchError(
                "Valuation provider lacks batch capability",
                code="REHEARSAL_PROVIDER_UNAVAILABLE",
            )
        for role, provider in (("quote", quotes), ("valuation", valuations)):
            if (
                not isinstance(provider, _SourceIdentity)
                or provider.provider_source() != by_role[role].source
            ):
                raise DataFetchError(
                    "Provider identity changed", code="REHEARSAL_PROVIDER_IDENTITY_MISMATCH"
                )
        with _RuntimeMonitor(backend_pid=backend_pid) as monitor:
            with RehearsalHttpCapture(
                max_dispatches=max_dispatches,
                max_seconds=task_deadline_seconds,
            ) as capture:
                valuation_facts = valuations.fetch_current_valuations(
                    list(registered_universe), target_trade_date
                )
                valuation_coverage = _fact_coverage(
                    valuation_facts,
                    requested=registered_universe,
                    target_trade_date=target_trade_date,
                )
                excluded_codes = tuple(
                    cast(list[str], valuation_coverage["missing_target_session_codes"])
                )
                eligible_codes = tuple(sorted(set(registered_universe) - set(excluded_codes)))
                if not eligible_codes:
                    raise DataFetchError(
                        "Valuation scope has no eligible assets",
                        code="REHEARSAL_CAPACITY_ELIGIBLE_SCOPE_EMPTY",
                    )
                quote_facts = quotes.fetch_quote_snapshots_for_session(
                    list(eligible_codes), target_trade_date
                )
    finished = datetime.now(UTC)
    if monitor.error_code:
        raise DataFetchError("Capacity runtime monitor failed", code=monitor.error_code)
    if not quote_facts or not valuation_facts or not capture.receipts:
        raise DataFetchError(
            "Full-universe provider exercise returned no usable facts",
            code="REHEARSAL_CAPACITY_PROVIDER_EMPTY",
        )
    if any(item.error_code or item.status_code != 200 for item in capture.receipts):
        raise DataFetchError(
            "Full-universe provider transport failed",
            code="REHEARSAL_CAPACITY_PROVIDER_FAILED",
        )
    elapsed = (finished - started).total_seconds()
    memory_limit = _memory_limit_bytes()
    asset_codes = list(registered_universe)
    quote_coverage = _fact_coverage(
        quote_facts,
        requested=eligible_codes,
        target_trade_date=target_trade_date,
    )
    valuation_coverage_ratio = len(eligible_codes) / len(registered_universe)
    if valuation_coverage_ratio < valuation_policy.minimum_coverage_ratio:
        raise DataFetchError(
            "Valuation scope does not satisfy the active publication policy",
            code="REHEARSAL_CAPACITY_VALUATION_COVERAGE_LOW",
        )
    if quote_coverage["missing_target_session_count"] != 0:
        raise DataFetchError(
            "Eligible quote scope is incomplete for the target session",
            code="REHEARSAL_CAPACITY_QUOTE_SCOPE_INCOMPLETE",
        )
    universe_digest = hashlib.sha256(
        json.dumps(asset_codes, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    identity_digest = rehearsal_identities_digest(identities)
    receipt: dict[str, object] = {
        "schema": "release.full-universe-capacity-receipt.v1",
        "measurement_source": "candidate_runtime_instrumentation",
        "measurement_scope": "production_valuation_seed_and_eligible_quote_dispatch",
        "candidate_sha": candidate_sha,
        "candidate_image_id": candidate_image_id,
        "target_trade_date": target_trade_date.isoformat(),
        "universe_sha256": universe_digest,
        "provider_identities_sha256": identity_digest,
        "outcome": "success",
        "asset_codes": asset_codes,
        "requested_asset_count": len(asset_codes),
        "measured_asset_count": len(asset_codes),
        "registered_asset_count": len(registered_universe),
        "eligible_asset_count": len(eligible_codes),
        "eligible_asset_codes": list(eligible_codes),
        "excluded_asset_count": len(excluded_codes),
        "excluded_asset_codes": list(excluded_codes),
        "exclusion_reason": "valuation_not_returned_for_target_session",
        "valuation_minimum_coverage_ratio": valuation_policy.minimum_coverage_ratio,
        "valuation_coverage_ratio": valuation_coverage_ratio,
        "valuation_policy_identity": valuation_policy.identity,
        "valuation_policy_sha256": valuation_policy_sha256,
        "valuation_policy_snapshot": valuation_policy_snapshot,
        "exclusion_rule_version": "valuation-target-session-v1",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_seconds": elapsed,
        "provider_total_requests": len(capture.receipts),
        "provider_peak_requests_per_window": _peak_requests(
            capture.receipts, provider_window_seconds
        ),
        "provider_request_limit_per_window": provider_request_limit_per_window,
        "provider_window_seconds": provider_window_seconds,
        "task_deadline_seconds": task_deadline_seconds,
        "database_peak_connections": monitor.database_peak_connections,
        "database_connection_limit": monitor.database_connection_limit,
        "database_connection_scope": "postgresql_cluster_all_databases",
        "database_peak_measurement_method": "sampled_pg_stat_activity_cluster_count",
        "sampling_interval_seconds": monitor.interval_seconds,
        "max_lock_wait_seconds": monitor.max_lock_wait_seconds,
        "lock_wait_limit_seconds": lock_wait_limit_seconds,
        "peak_memory_bytes": monitor.peak_memory_bytes,
        "memory_limit_bytes": memory_limit,
        "memory_peak_measurement_method": "linux_proc_status_vmhwm",
        "memory_limit_measurement_method": "cgroup_effective_or_host_physical",
        "minimum_capacity_margin_ratio": minimum_capacity_margin,
        "quote_fact_count": len(quote_facts),
        "valuation_fact_count": len(valuation_facts),
        "quote_coverage": quote_coverage,
        "valuation_coverage": valuation_coverage,
        "source_tree_sha256": source_digest,
        "candidate_source_attestation": source_attestation,
    }
    peak_requests = _peak_requests(capture.receipts, provider_window_seconds)
    ratios = (
        peak_requests / provider_request_limit_per_window,
        elapsed / task_deadline_seconds,
        monitor.database_peak_connections / monitor.database_connection_limit,
        monitor.max_lock_wait_seconds / lock_wait_limit_seconds,
        monitor.peak_memory_bytes / memory_limit,
    )
    if any(ratio > 1.0 - minimum_capacity_margin for ratio in ratios):
        raise DataFetchError(
            "Measured capacity exceeded a release limit",
            code="REHEARSAL_CAPACITY_LIMIT_EXCEEDED",
        )
    verify_configured_rehearsal_identities(identities)
    if market_rehearsal_source_digest(source_root) != source_digest:
        raise DataFetchError(
            "Candidate source changed during capacity measurement",
            code="REHEARSAL_CAPACITY_SOURCE_CHANGED",
        )
    final_attestation, final_image_id = verify_candidate_release_image(source_root, candidate_sha)
    if final_attestation != source_attestation or final_image_id != candidate_image_id:
        raise DataFetchError(
            "Candidate image identity changed during capacity measurement",
            code="REHEARSAL_CAPACITY_CANDIDATE_IMAGE_CHANGED",
        )
    output_dir.mkdir(parents=True, exist_ok=False)
    receipt_digest = _write_json(output_dir / "full-universe-capacity-receipt.json", receipt)
    report: dict[str, object] = {
        "schema": "release.full-universe-capacity.v2",
        "kind": "full_universe_capacity",
        "evidence_mode": "measured_full_universe",
        "candidate_sha": candidate_sha,
        "candidate_image_id": candidate_image_id,
        "target_trade_date": target_trade_date.isoformat(),
        "universe_sha256": universe_digest,
        "provider_identities_sha256": identity_digest,
        "outcome": "success",
        "candidate_source_attestation": source_attestation,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "universe_count": len(asset_codes),
        "measured_asset_count": len(asset_codes),
        "asset_codes": asset_codes,
        "measurement_artifact": {
            "path": "full-universe-capacity-receipt.json",
            "sha256": receipt_digest,
        },
        "eligible_asset_count": len(eligible_codes),
        "eligible_asset_codes": list(eligible_codes),
        "excluded_asset_count": len(excluded_codes),
        "excluded_asset_codes": list(excluded_codes),
        "exclusion_reason": "valuation_not_returned_for_target_session",
        "exclusion_rule_version": "valuation-target-session-v1",
        "valuation_policy_identity": valuation_policy.identity,
        "valuation_policy_sha256": valuation_policy_sha256,
        "valuation_policy_snapshot": valuation_policy_snapshot,
        "valuation_minimum_coverage_ratio": valuation_policy.minimum_coverage_ratio,
        "provider_quota_within_limit": True,
        "task_deadline_within_limit": True,
        "database_budget_within_limit": True,
        "lock_budget_within_limit": True,
        "memory_budget_within_limit": True,
        "capacity_margin_ratio": min(1.0 - ratio for ratio in ratios),
    }
    _write_json(output_dir / "full-universe-capacity.json", report)
    return report
