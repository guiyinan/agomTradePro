"""Typed Data Center fetch-event contract for the unified audit ledger.

This module deliberately stops at the application boundary.  It does not
read Django models, invent run identities, or open a transaction.  A future
same-alias coordinator must provide the batch/run identifiers, exact RawAudit
reference and stream head before calling :func:`build_data_fetch_audit_event`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditScopeRef,
    AuditSeverity,
    AuditWritePolicy,
    JSONValue,
    SystemAuditEvent,
)

_HASH_LENGTH: Final[int] = 64
_EVENT_VERSION: Final[str] = "1"
_SCHEMA_BY_OUTCOME: Final[dict[AuditOutcome, str]] = {
    AuditOutcome.SUCCESS: "data.fetch.completed.v1",
    AuditOutcome.NOOP: "data.fetch.noop.v1",
    AuditOutcome.FAILED: "data.fetch.failed.v1",
}
_EVENT_TYPE_BY_OUTCOME: Final[dict[AuditOutcome, str]] = {
    AuditOutcome.SUCCESS: "data.fetch.completed",
    AuditOutcome.NOOP: "data.fetch.noop",
    AuditOutcome.FAILED: "data.fetch.failed",
}
_REASON_BY_OUTCOME: Final[dict[AuditOutcome, str]] = {
    AuditOutcome.SUCCESS: "fetch_completed",
    AuditOutcome.NOOP: "fetch_noop",
    AuditOutcome.FAILED: "fetch_failed",
}


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{field_name} must be a bounded non-empty string")


def _require_digest(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DataFetchAuditObservation:
    """Immutable outcome and exact references for one fetch batch."""

    provider_key: str
    capability: str
    dataset_key: str
    run_id: str
    ingested_run_id: str
    raw_audit_id: str
    raw_audit_version: str
    raw_audit_content_hash: str
    outcome: AuditOutcome
    row_count: int
    recorded_at: datetime
    occurred_at: datetime
    observed_at: datetime | None = None
    error_class: str | None = None
    scope: AuditScopeRef | None = None

    def __post_init__(self) -> None:
        for name in (
            "provider_key",
            "capability",
            "dataset_key",
            "run_id",
            "ingested_run_id",
            "raw_audit_id",
            "raw_audit_version",
        ):
            _require_identifier(getattr(self, name), name)
        _require_digest(self.raw_audit_content_hash, "raw_audit_content_hash")
        if self.outcome not in _SCHEMA_BY_OUTCOME:
            raise ValueError("data fetch audit outcome must be success, noop or failed")
        if not isinstance(self.row_count, int) or isinstance(self.row_count, bool):
            raise ValueError("row_count must be an integer")
        if self.row_count < 0:
            raise ValueError("row_count cannot be negative")
        if self.outcome is AuditOutcome.SUCCESS and self.row_count <= 0:
            raise ValueError("successful fetch event requires at least one row")
        if self.outcome in {AuditOutcome.NOOP, AuditOutcome.FAILED} and self.row_count != 0:
            raise ValueError("noop/failed fetch event must have zero rows")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.observed_at is not None:
            _require_aware(self.observed_at, "observed_at")
            if self.observed_at > self.recorded_at:
                raise ValueError("observed_at cannot be after recorded_at")
        if self.error_class is not None:
            _require_identifier(self.error_class, "error_class")
        if self.outcome is AuditOutcome.FAILED and not self.error_class:
            raise ValueError("failed fetch event requires an error class")


def _stable_event_id(observation: DataFetchAuditObservation) -> str:
    material = "|".join(
        (
            observation.run_id,
            observation.ingested_run_id,
            observation.dataset_key,
            observation.provider_key,
            observation.capability,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-fetch-{digest}"


def build_data_fetch_audit_event(
    observation: DataFetchAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build a canonical fetch event from owner-provided stream state.

    ``sequence_no`` and ``predecessor_hash`` are intentionally required: the
    builder cannot safely select or fabricate a stream head.  The future
    coordinator must obtain them in the same alias transaction as the event
    and outbox append.
    """

    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    outcome = observation.outcome
    detail: dict[str, JSONValue] = {"row_count": observation.row_count}
    if observation.error_class is not None:
        detail["error_class"] = observation.error_class
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=_EVENT_TYPE_BY_OUTCOME[outcome],
        owner="data_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=outcome,
        severity=(
            AuditSeverity.ERROR
            if outcome is AuditOutcome.FAILED
            else (AuditSeverity.WARNING if outcome is AuditOutcome.NOOP else AuditSeverity.INFO)
        ),
        reason_codes=(_REASON_BY_OUTCOME[outcome],),
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=observation.observed_at,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="sync",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            ingested_run_id=observation.ingested_run_id,
            dataset_key=observation.dataset_key,
            provider_key=observation.provider_key,
            capability=observation.capability,
        ),
        resource=AuditResourceRef(
            "raw_audit",
            observation.raw_audit_id,
            observation.raw_audit_version,
        ),
        dataset_key=observation.dataset_key,
        provider_key=observation.provider_key,
        capability=observation.capability,
        publication_id=None,
        evidence_refs=(
            AuditEvidenceRef(
                "data_center",
                "raw_audit",
                observation.raw_audit_id,
                observation.raw_audit_version,
                observation.raw_audit_content_hash,
            ),
        ),
        detail_schema=_SCHEMA_BY_OUTCOME[outcome],
        detail=detail,
        stream_id=f"data.fetch:{observation.dataset_key}",
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=(
            f"data-fetch:{observation.run_id}:{observation.ingested_run_id}:"
            f"{observation.dataset_key}"
        ),
        scope=observation.scope,
    )


__all__ = ["DataFetchAuditObservation", "build_data_fetch_audit_event"]
