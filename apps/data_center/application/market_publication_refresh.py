"""Refresh complete market facts before publishing the frozen market scope."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
class MarketPriceSuspensionEvidence:
    """Bind one asset's price omission to target-session provider evidence."""

    asset_code: str
    target_trade_date: date
    evidence_source: str

    def __post_init__(self) -> None:
        """Reject incomplete or non-canonical target-date suspension evidence."""

        if (
            not isinstance(self.asset_code, str)
            or not self.asset_code
            or self.asset_code != self.asset_code.strip().upper()
        ):
            raise ValueError("price suspension asset code must be canonical")
        if not isinstance(self.target_trade_date, date) or isinstance(
            self.target_trade_date, datetime
        ):
            raise ValueError("price suspension target date must be a date")
        if (
            not isinstance(self.evidence_source, str)
            or not self.evidence_source
            or self.evidence_source != self.evidence_source.strip()
        ):
            raise ValueError("price suspension evidence source must be canonical")


@dataclass(frozen=True)
class MarketPricePreparationResult:
    """Verified target prices and complete request plus selected-member audit evidence."""

    suspended_codes: tuple[str, ...]
    raw_audit_references: tuple[RawAuditReference, ...]
    suspension_evidence: tuple[MarketPriceSuspensionEvidence, ...] = ()
    # Complete request-level diagnostics, including successful empty batches.
    raw_audit_bindings: tuple[ModelHistoryRawAuditBinding, ...] = ()
    # Exact source bindings returned for rows that satisfied the target-session check.
    member_owning_raw_audit_bindings: tuple[ModelHistoryRawAuditBinding, ...] = ()

    def __post_init__(self) -> None:
        """Keep the returned suspension scope and evidence references deterministic."""

        if tuple(sorted(set(self.suspended_codes))) != self.suspended_codes:
            raise ValueError("suspended codes must be sorted and unique")
        evidence_codes = tuple(item.asset_code for item in self.suspension_evidence)
        if tuple(sorted(set(evidence_codes))) != evidence_codes:
            raise ValueError("suspension evidence must be sorted and unique")
        if evidence_codes != self.suspended_codes:
            raise ValueError("suspension evidence must exactly match suspended codes")
        if len({item.target_trade_date for item in self.suspension_evidence}) > 1:
            raise ValueError("price suspension evidence must bind one target date")
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

        member_bindings_by_id: dict[str, ModelHistoryRawAuditBinding] = {}
        for binding in self.member_owning_raw_audit_bindings:
            reference_id = binding.reference.raw_audit_id
            prior = member_bindings_by_id.get(reference_id)
            if prior is not None and prior != binding:
                code = (
                    "MODEL_MARKET_AUDIT_SOURCE_TYPE_CONFLICT"
                    if prior.source_type != binding.source_type
                    else "MODEL_MARKET_AUDIT_REFERENCE_CONFLICT"
                )
                raise DataFetchError(
                    "Repeated member-owning price RawAudit has conflicting lineage",
                    code=code,
                    details={"raw_audit_id": reference_id},
                )
            member_bindings_by_id[reference_id] = binding
        member_binding_ids = tuple(
            binding.reference.raw_audit_id for binding in self.member_owning_raw_audit_bindings
        )
        if tuple(sorted(set(member_binding_ids))) != member_binding_ids:
            raise ValueError("member-owning price audit bindings must be sorted and unique")
        missing_member_ids: list[str] = []
        for reference_id, member_binding in member_bindings_by_id.items():
            diagnostic_binding = bindings_by_id.get(reference_id)
            if diagnostic_binding is None:
                missing_member_ids.append(reference_id)
                continue
            if diagnostic_binding != member_binding:
                code = (
                    "MODEL_MARKET_AUDIT_SOURCE_TYPE_CONFLICT"
                    if diagnostic_binding.source_type != member_binding.source_type
                    else "MODEL_MARKET_AUDIT_REFERENCE_CONFLICT"
                )
                raise DataFetchError(
                    "Member-owning price RawAudit conflicts with request diagnostics",
                    code=code,
                    details={"raw_audit_id": reference_id},
                )
        if missing_member_ids:
            raise DataFetchError(
                "Member-owning price RawAudit is absent from request diagnostics",
                code="MODEL_MARKET_AUDIT_EVIDENCE_MISSING",
                details={"raw_audit_ids": sorted(missing_member_ids)},
            )


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
    suspension_evidence: dict[str, MarketPriceSuspensionEvidence] = {}
    member_bindings: dict[str, ModelHistoryRawAuditBinding] = {}
    diagnostic_bindings: dict[str, ModelHistoryRawAuditBinding] = {}

    def collect_bindings(
        destination: dict[str, ModelHistoryRawAuditBinding],
        new_bindings: tuple[ModelHistoryRawAuditBinding, ...],
    ) -> None:
        """Deduplicate exact references while rejecting conflicting source metadata."""

        for binding in new_bindings:
            reference_id = binding.reference.raw_audit_id
            prior = destination.get(reference_id)
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
            destination[reference_id] = binding

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
        collect_bindings(member_bindings, evidence_port.model_history_audit_bindings(rows))

    for code in asset_codes:
        try:
            rows = port.stock_history(code, target_date, target_date)
            if not rows or max(row.trade_date for row in rows) != target_date:
                raise DataFetchError(
                    "Current price observations missing", code="MODEL_MARKET_STALE"
                )
            collect_references(rows)
        except DataFetchError as exc:
            suspension_error: DataFetchError | None = None
            if exc.code == "MODEL_MARKET_SUSPENDED":
                if (
                    exc.details.get("asset_code") != code
                    or exc.details.get("suspended_through") != target_date.isoformat()
                ):
                    raise
                suspension_error = exc
            else:
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
                    suspension_error = history_error
            if suspension_error is None:
                raise DataFetchError(
                    "Target-session suspension evidence is unavailable",
                    code="MODEL_MARKET_SUSPENSION_EVIDENCE_INVALID",
                    details={"asset_code": code, "target_trade_date": target_date.isoformat()},
                ) from exc
            evidence_source = suspension_error.details.get("source")
            if (
                not isinstance(evidence_source, str)
                or not evidence_source
                or evidence_source != evidence_source.strip()
            ):
                raise DataFetchError(
                    "Target-session suspension evidence lacks a canonical provider source",
                    code="MODEL_MARKET_SUSPENSION_EVIDENCE_INVALID",
                    details={"asset_code": code, "target_trade_date": target_date.isoformat()},
                ) from exc
            suspended.append(code)
            suspension_evidence[code] = MarketPriceSuspensionEvidence(
                asset_code=code,
                target_trade_date=target_date,
                evidence_source=evidence_source,
            )
    if audit_evidence is not None:
        collect_bindings(
            diagnostic_bindings,
            audit_evidence.take_model_history_audit_bindings(),
        )
    ordered_diagnostic_bindings = tuple(
        diagnostic_bindings[key] for key in sorted(diagnostic_bindings)
    )
    ordered_member_bindings = tuple(member_bindings[key] for key in sorted(member_bindings))
    ordered_references = tuple(binding.reference for binding in ordered_diagnostic_bindings)
    return MarketPricePreparationResult(
        suspended_codes=tuple(sorted(suspended)),
        raw_audit_references=ordered_references,
        suspension_evidence=tuple(
            suspension_evidence[code] for code in sorted(suspension_evidence)
        ),
        raw_audit_bindings=ordered_diagnostic_bindings,
        member_owning_raw_audit_bindings=ordered_member_bindings,
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
