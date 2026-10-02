"""Refresh complete market facts before publishing the frozen market scope."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial
from typing import TypedDict

from apps.data_center.application.model_market_data import (
    ModelHistoryAuditEvidencePort,
    ModelHistoryRawAuditBinding,
)
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.model_market_data import (
    ModelDailyBar,
    ModelHistoryPreparationPort,
    ModelMarketDataPort,
)
from core.exceptions import DataFetchError

from .batch_identity import ProviderAssetIdentityError

logger = logging.getLogger(__name__)


class MarketPublicationRefreshBlocked(DataFetchError):
    """Stop a refresh when a task-wide prerequisite becomes unavailable."""

    default_message = "Current Audit authority is unavailable before a market write"
    default_code = "authority_changed_or_expired"


class _PhaseResult(TypedDict):
    phase: str
    requested: int
    succeeded: int
    failed: int
    stored: int


@dataclass(frozen=True)
class MarketPricePreparationResult:
    """Verified target prices and the exact RawAudit references that supplied them."""

    suspended_codes: tuple[str, ...]
    raw_audit_references: tuple[RawAuditReference, ...]
    raw_audit_bindings: tuple[ModelHistoryRawAuditBinding, ...] = ()

    def __post_init__(self) -> None:
        """Keep the returned suspension scope and evidence references deterministic."""

        if tuple(sorted(set(self.suspended_codes))) != self.suspended_codes:
            raise ValueError("suspended codes must be sorted and unique")
        reference_ids = tuple(reference.raw_audit_id for reference in self.raw_audit_references)
        if tuple(sorted(set(reference_ids))) != reference_ids:
            raise ValueError("price audit references must be sorted and unique")
        bindings_by_id: dict[str, ModelHistoryRawAuditBinding] = {}
        for binding in self.raw_audit_bindings:
            reference_id = binding.reference.raw_audit_id
            prior = bindings_by_id.get(reference_id)
            if prior is not None and prior != binding:
                code = (
                    "MODEL_MARKET_AUDIT_SOURCE_TYPE_CONFLICT"
                    if prior.source_type != binding.source_type
                    else "MODEL_MARKET_AUDIT_REFERENCE_CONFLICT"
                )
                raise DataFetchError(
                    "Repeated price RawAudit reference has conflicting lineage",
                    code=code,
                    details={"raw_audit_id": reference_id},
                )
            bindings_by_id[reference_id] = binding
        binding_ids = tuple(binding.reference.raw_audit_id for binding in self.raw_audit_bindings)
        if tuple(sorted(set(binding_ids))) != binding_ids:
            raise ValueError("price audit bindings must be sorted and unique")
        if (
            self.raw_audit_bindings
            and tuple(binding.reference for binding in self.raw_audit_bindings)
            != self.raw_audit_references
        ):
            raise ValueError("price audit references must match their source-bound bindings")


def refresh_market_price_inputs(
    port: ModelMarketDataPort, asset_codes: list[str], target_date: date
) -> MarketPricePreparationResult:
    """Verify target-session prices, expanding only missing assets for suspension proof."""
    history_start = target_date - timedelta(days=120)
    audit_evidence = port if isinstance(port, ModelHistoryAuditEvidencePort) else None
    if audit_evidence is not None:
        audit_evidence.take_model_history_audit_bindings()
    if isinstance(port, ModelHistoryPreparationPort):
        port.prepare_stock_history(tuple(asset_codes), target_date, target_date)
    suspended: list[str] = []
    bindings: dict[str, ModelHistoryRawAuditBinding] = {}

    def collect_bindings(new_bindings: tuple[ModelHistoryRawAuditBinding, ...]) -> None:
        """Deduplicate exact references while rejecting conflicting source metadata."""

        for binding in new_bindings:
            reference_id = binding.reference.raw_audit_id
            prior = bindings.get(reference_id)
            if prior is not None and prior != binding:
                code = (
                    "MODEL_MARKET_AUDIT_SOURCE_TYPE_CONFLICT"
                    if prior.source_type != binding.source_type
                    else "MODEL_MARKET_AUDIT_REFERENCE_CONFLICT"
                )
                raise DataFetchError(
                    "Repeated price RawAudit reference has conflicting lineage",
                    code=code,
                    details={"raw_audit_id": reference_id},
                )
            bindings[reference_id] = binding

    def collect_references(rows: tuple[ModelDailyBar, ...]) -> None:
        """Collect exact evidence only after the returned rows pass date checks."""

        if not rows:
            return
        evidence_port = audit_evidence
        if evidence_port is None:
            raise DataFetchError(
                "Verified model-history rows lack exact RawAudit evidence",
                code="MODEL_MARKET_AUDIT_EVIDENCE_MISSING",
            )
        collect_bindings(evidence_port.model_history_audit_bindings(rows))

    for code in asset_codes:
        try:
            rows = port.stock_history(code, target_date, target_date)
            if not rows or max(row.trade_date for row in rows) != target_date:
                raise DataFetchError(
                    "Current price observations missing", code="MODEL_MARKET_STALE"
                )
            collect_references(rows)
        except DataFetchError as exc:
            if (
                exc.code != "MODEL_MARKET_SUSPENDED"
                or exc.details.get("asset_code") != code
                or exc.details.get("suspended_through") != target_date.isoformat()
            ):
                if exc.code not in {"MODEL_MARKET_UNAVAILABLE", "MODEL_MARKET_STALE"}:
                    raise
                try:
                    if isinstance(port, ModelHistoryPreparationPort):
                        port.prepare_stock_history((code,), history_start, target_date)
                    rows = port.stock_history(code, history_start, target_date)
                    if rows and max(row.trade_date for row in rows) == target_date:
                        collect_references(rows)
                        continue
                    raise DataFetchError(
                        "Current price observations missing", code="MODEL_MARKET_STALE"
                    )
                except DataFetchError as history_error:
                    if (
                        history_error.code != "MODEL_MARKET_SUSPENDED"
                        or history_error.details.get("asset_code") != code
                        or history_error.details.get("suspended_through") != target_date.isoformat()
                    ):
                        raise
            suspended.append(code)
    if audit_evidence is not None:
        collect_bindings(audit_evidence.take_model_history_audit_bindings())
    ordered_bindings = tuple(bindings[key] for key in sorted(bindings))
    ordered_references = tuple(binding.reference for binding in ordered_bindings)
    return MarketPricePreparationResult(
        suspended_codes=tuple(sorted(suspended)),
        raw_audit_references=ordered_references,
        raw_audit_bindings=ordered_bindings,
    )


@dataclass(frozen=True)
class MarketPublicationRefreshPorts:
    """Factories inject audited fact-only sync and the atomic publication coordinator."""

    list_codes: Callable[[], list[str]]
    sync_quotes: Callable[[list[str]], int]
    sync_valuations: Callable[[list[str], date], int]
    publish: Callable[[list[str]], int]


def refresh_market_publications(
    *, ports: MarketPublicationRefreshPorts, as_of_date: date, batch_size: int = 100
) -> dict[str, object]:
    """Publish only after every fact batch succeeds; counts measure sync operations."""
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 200
    ):
        raise ValueError("batch_size must be an integer from 1 to 200")
    if not isinstance(as_of_date, date):
        raise ValueError("as_of_date must be a date")
    codes = sorted(set(ports.list_codes()))
    requested = ((len(codes) + batch_size - 1) // batch_size) * 2 + 1 if codes else 0
    batches = (len(codes) + batch_size - 1) // batch_size
    phases: list[_PhaseResult] = [
        {"phase": name, "requested": total, "succeeded": 0, "failed": 0, "stored": 0}
        for name, total in (
            ("quote", batches),
            ("valuation", batches),
            ("publication", int(bool(codes))),
        )
    ]
    failed_phase = ""
    terminal_blocked = False
    succeeded = failed = stored = 0
    errors: list[str] = []
    for offset in range(0, len(codes), batch_size):
        batch = codes[offset : offset + batch_size]
        operations: tuple[Callable[[], int], ...] = (
            partial(ports.sync_quotes, batch),
            partial(ports.sync_valuations, batch, as_of_date),
        )
        for phase, operation in zip(phases[:2], operations, strict=True):
            try:
                count = operation()
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise DataFetchError("Invalid stored count", code="MARKET_STORED_COUNT_INVALID")
                stored += count
                phase["stored"] += count
                if count != len(batch):
                    raise DataFetchError("Market batch incomplete", code="MARKET_BATCH_INCOMPLETE")
                succeeded += 1
                phase["succeeded"] += 1
            except (
                DataFetchError,
                ProviderAssetIdentityError,
                OSError,
                RuntimeError,
                ValueError,
            ) as exc:
                failed += 1
                phase["failed"] += 1
                failed_phase = failed_phase or phase["phase"]
                errors.append(getattr(exc, "code", type(exc).__name__))
                logger.exception(
                    "Market refresh phase failed: phase=%s offset=%s", phase["phase"], offset
                )
                if isinstance(exc, MarketPublicationRefreshBlocked):
                    terminal_blocked = True
                    break
        if terminal_blocked:
            break
    if terminal_blocked:
        for phase in phases:
            phase["failed"] = phase["requested"] - phase["succeeded"]
        failed = requested - succeeded
    published = 0
    if codes and failed == 0:
        try:
            publication_count = ports.publish(codes)
            if (
                isinstance(publication_count, bool)
                or not isinstance(publication_count, int)
                or publication_count <= 0
            ):
                raise DataFetchError(
                    "Market publication returned an invalid member count",
                    code="MARKET_PUBLICATION_COUNT_INVALID",
                )
            published = publication_count
            succeeded += 1
            phases[2]["succeeded"] = 1
        except (DataFetchError, OSError, RuntimeError, ValueError) as exc:
            failed += 1
            phases[2]["failed"] = 1
            failed_phase = "publication"
            errors.append(str(getattr(exc, "code", "") or "MARKET_PUBLICATION_VALIDATION_FAILED"))
            if isinstance(exc, MarketPublicationRefreshBlocked):
                terminal_blocked = True
            logger.exception("Market publication validation failed for target_date=%s", as_of_date)
    elif codes and not terminal_blocked:
        failed += 1
        phases[2]["failed"] = 1
        errors.append("market_publication_skipped_incomplete_refresh")
    if terminal_blocked:
        outcome = "partial" if stored else "blocked"
    elif published:
        outcome = "success"
    elif stored:
        outcome = "partial"
    else:
        outcome = "failed"
    result: dict[str, object] = {
        "outcome": outcome,
        "success": outcome == "success",
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "stored": stored,
        "count_unit": "sync_operation",
        "stored_count_unit": "fact_row",
        "target_trade_date": as_of_date.isoformat(),
        "phase": failed_phase or ("completed" if published else "scope"),
        "phase_results": phases,
        "asset_count": len(codes),
        "published_members": published,
        "publication_updated": bool(published),
        "errors": errors or ([] if codes else ["market_scope_empty"]),
    }
    if errors:
        result["error_code"] = errors[0]
        result["blocked_reason"] = errors[0]
    if terminal_blocked:
        result["must_not_use_for_decision"] = True
    return result
