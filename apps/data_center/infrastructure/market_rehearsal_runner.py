"""Read-only PostgreSQL and real-provider composition for market rehearsals."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from django.db import connection, transaction

from apps.data_center.application.market_calendar import latest_completed_cn_market_session
from apps.data_center.application.market_provider_rehearsal import (
    assess_market_probe,
    rehearsal_digest,
    select_rehearsal_sample,
)
from apps.data_center.application.query_services import list_active_stock_codes_for_backfill
from apps.data_center.composition import get_provider_registry
from apps.data_center.domain.entities import QuoteSnapshot, ValuationFact
from apps.data_center.domain.protocols import CurrentValuationBatchProviderProtocol
from core.exceptions import AgomTradeProException, DataFetchError

from .rehearsal_http_capture import RehearsalHttpCapture


def market_rehearsal_source_digest(root: Path) -> str:
    """Bind actual provider/application source and dependency manifests inside the candidate."""
    if any(not (root / directory).is_dir() for directory in ("apps", "core", "shared")):
        raise ValueError("candidate source tree is incomplete")
    files = sorted(
        path
        for directory in ("apps", "core", "shared")
        for path in (root / directory).rglob("*.py")
        if "__pycache__" not in path.parts
    )
    files.extend(root / name for name in ("pyproject.toml", "requirements-prod.txt"))
    if not files or any(not path.is_file() for path in files):
        raise ValueError("candidate source tree is incomplete")
    manifest = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    return rehearsal_digest(manifest)


def _probe(
    *,
    dataset: str,
    fetch: Callable[[], list[QuoteSnapshot] | list[ValuationFact]],
    sample: tuple[str, ...],
    target_date: date,
    capture: RehearsalHttpCapture,
) -> dict[str, object]:
    started = datetime.now(UTC)
    receipt_start = len(capture.receipts)
    facts: list[QuoteSnapshot] | list[ValuationFact] = []
    try:
        facts = fetch()
        result = assess_market_probe(
            dataset=dataset,
            facts=facts,
            sample=sample,
            target_date=target_date,
            started_at=started,
            finished_at=datetime.now(UTC),
        )
    except (AgomTradeProException, OSError, RuntimeError, ValueError, TypeError) as exc:
        # Provider exception text may contain transport credentials. Keep it out of artifacts.
        error_code = (
            exc.code
            if isinstance(exc, AgomTradeProException)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,127}", exc.code)
            else "REHEARSAL_PROVIDER_FAILED"
        )
        result = {
            "dataset": dataset,
            "outcome": "failed",
            "requested": len(sample),
            "succeeded": 0,
            "failed": len(sample),
            "stored": 0,
            "issues": [{"code": error_code}],
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "publication_updated": False,
        }
    receipts = capture.receipts[receipt_start:]
    result["receipt_indexes"] = list(range(receipt_start, len(capture.receipts)))
    if not any(
        receipt.status_code == 200 and receipt.body_bytes > 0 and not receipt.error_code
        for receipt in receipts
    ):
        result["outcome"] = "blocked"
        result["transport_error_code"] = "REHEARSAL_REAL_RESPONSE_MISSING"
    if any(receipt.error_code for receipt in receipts):
        result["outcome"] = "blocked"
        result["transport_error_code"] = "REHEARSAL_TRANSPORT_FAILURE"
    response_hashes = {receipt.body_sha256 for receipt in receipts if receipt.body_sha256}
    if any(
        isinstance(fact, ValuationFact) and fact.raw_payload_hash not in response_hashes
        for fact in facts
    ):
        result["outcome"] = "blocked"
        result["transport_error_code"] = "REHEARSAL_SOURCE_RESPONSE_MISMATCH"
    return result


def run_market_provider_rehearsal(
    *,
    quote_provider_id: int,
    valuation_provider_id: int,
    candidate_sha: str,
    source_root: Path,
    sample_size: int = 50,
    max_dispatches: int = 100,
    max_seconds: float = 180.0,
) -> dict[str, object]:
    """Probe configured live providers in a database-enforced read-only transaction.

    This command reports provider-read evidence only. Release eligibility also
    requires independent capacity, source-unit, staging-write and regression
    evidence; the probe must never substitute for that combined gate.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", candidate_sha):
        raise ValueError("candidate_sha must be a full lowercase commit SHA")
    if connection.vendor != "postgresql" or connection.in_atomic_block:
        raise DataFetchError(
            "Rehearsal requires a fresh PostgreSQL transaction",
            code="REHEARSAL_READ_ONLY_UNAVAILABLE",
        )
    if min(quote_provider_id, valuation_provider_id) <= 0:
        raise ValueError("explicit configured provider ids are required")
    started = datetime.now(UTC)
    source_digest = market_rehearsal_source_digest(source_root)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", ["30000"])
        universe = tuple(sorted(set(list_active_stock_codes_for_backfill())))
        sample = select_rehearsal_sample(universe, sample_size)
        target_date: date | None = None
        stage_error_code = ""
        probes: list[dict[str, object]] = []
        with RehearsalHttpCapture(
            max_dispatches=max_dispatches, max_seconds=max_seconds
        ) as capture:
            try:
                target_date = latest_completed_cn_market_session(started)
            except (
                AgomTradeProException,
                OSError,
                PermissionError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                stage_error_code = "REHEARSAL_CALENDAR_UNAVAILABLE"
            if target_date is None:
                stage_error_code = stage_error_code or "REHEARSAL_SESSION_UNAVAILABLE"
            elif not stage_error_code:
                try:
                    registry = get_provider_registry()
                    quotes = registry.get_by_id(quote_provider_id)
                    valuations = registry.get_by_id(valuation_provider_id)
                except (
                    AgomTradeProException,
                    OSError,
                    PermissionError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                ):
                    stage_error_code = "REHEARSAL_PROVIDER_SETUP_FAILED"
                    quotes = None
                    valuations = None
                if quotes is None or not isinstance(
                    valuations, CurrentValuationBatchProviderProtocol
                ):
                    stage_error_code = stage_error_code or "REHEARSAL_PROVIDER_UNAVAILABLE"
                else:
                    probes = [
                        _probe(
                            dataset="equity.quote.snapshot",
                            fetch=lambda: quotes.fetch_quote_snapshots(list(sample)),
                            sample=sample,
                            target_date=target_date,
                            capture=capture,
                        ),
                        _probe(
                            dataset="equity.valuation.fact",
                            fetch=lambda: valuations.fetch_current_valuations(
                                list(sample), target_date
                            ),
                            sample=sample,
                            target_date=target_date,
                            capture=capture,
                        ),
                    ]
        transport = capture.to_dict()
        within_budget = time.monotonic() - capture.started <= max_seconds
    source_unchanged = source_digest == market_rehearsal_source_digest(source_root)
    outcome = (
        "success"
        if within_budget
        and source_unchanged
        and not stage_error_code
        and len(probes) == 2
        and all(probe["outcome"] == "success" for probe in probes)
        else "blocked"
    )
    return {
        "schema": "market.provider-rehearsal.v1",
        "mode": "read_only_live_provider",
        "candidate_sha": candidate_sha,
        "source_tree_sha256": source_digest,
        "source_unchanged": source_unchanged,
        "outcome": outcome,
        "release_ready": False,
        "remaining_release_gates": [
            "real_response_unit_replay",
            "full_universe_capacity",
            "isolated_write_rehearsal",
            "candidate_regression_evidence",
        ],
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "target_trade_date": target_date.isoformat() if target_date is not None else None,
        "stage_error_code": stage_error_code,
        "universe_count": len(universe),
        "universe_sha256": rehearsal_digest(universe),
        "sample": list(sample),
        "sample_sha256": rehearsal_digest(sample),
        "sample_size": len(sample),
        "quote_provider_id": quote_provider_id,
        "valuation_provider_id": valuation_provider_id,
        "probes": probes,
        "transport": transport,
        "stored": 0,
        "publication_updated": False,
        "database_read_only": True,
        "capacity_estimate": None,
        "capacity_note": "Transport dispatches are measured; vendor quota, full-scale locks and write cost need separate evidence.",
    }
