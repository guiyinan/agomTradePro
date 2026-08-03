"""Data Center ingestion control-plane value objects.

The control plane deliberately lives in the domain layer so that task runners,
HTTP adapters and repositories share one state machine and one set of
fail-closed invariants.  These objects contain no Django or provider concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any


class SyncRunStatus(str, Enum):
    """Lifecycle state for one dataset synchronization run."""

    REQUESTED = "requested"
    FETCHING = "fetching"
    RECEIVED = "received"
    VALIDATING = "validating"
    NORMALIZED = "normalized"
    RECONCILING = "reconciling"
    STORED = "stored"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"
    FAILED = "failed"


class SyncItemState(str, Enum):
    """State of an individual batch/checkpoint item."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    SKIPPED = "skipped"


class QuarantineResolution(str, Enum):
    """Allowed resolution states for a quarantined payload."""

    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class PublicationFactReference:
    """Canonical fact identity selected by a publication writer.

    The reference deliberately contains no ORM model. Ingestion adapters can
    return this value object after persisting facts, allowing the application
    publication service to bind one immutable member snapshot to the exact
    rows written by the sync run.
    """

    natural_key: str
    source: str
    source_record_id: str
    fact_table: str
    fact_pk: str
    observed_at: datetime
    raw_payload_hash: str = ""
    quality_status: str = "accepted"
    revision_number: int = 1

    def __post_init__(self) -> None:
        for name in ("natural_key", "source", "source_record_id", "fact_table", "fact_pk"):
            if not getattr(self, name).strip():
                raise ValueError(f"PublicationFactReference.{name} cannot be empty")
        _require_aware(self.observed_at, "PublicationFactReference.observed_at")
        if self.revision_number < 1:
            raise ValueError("PublicationFactReference.revision_number must be positive")


class PublicationState(str, Enum):
    """Canonical publication lifecycle."""

    CANDIDATE = "candidate"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    BLOCKED = "blocked"


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_nonnegative(value: int, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")


@dataclass(frozen=True)
class SyncRun:
    """Auditable, resumable execution of one dataset ingestion request."""

    run_id: str
    dataset_key: str
    trigger: str
    status: SyncRunStatus = SyncRunStatus.REQUESTED
    outcome: str = "blocked"
    requested: int = 0
    fetched: int = 0
    validated: int = 0
    quarantined: int = 0
    succeeded: int = 0
    failed: int = 0
    stored: int = 0
    published: int = 0
    unchanged: int = 0
    provider_name: str = ""
    contract_version: str = ""
    config_snapshot_hash: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    error_code: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("SyncRun.run_id cannot be empty")
        if not self.dataset_key.strip():
            raise ValueError("SyncRun.dataset_key cannot be empty")
        if not self.trigger.strip():
            raise ValueError("SyncRun.trigger cannot be empty")
        _require_aware(self.started_at, "SyncRun.started_at")
        if self.finished_at is not None:
            _require_aware(self.finished_at, "SyncRun.finished_at")
            if self.finished_at < self.started_at:
                raise ValueError("SyncRun.finished_at cannot precede started_at")
        for name in (
            "requested",
            "fetched",
            "validated",
            "quarantined",
            "succeeded",
            "failed",
            "stored",
            "published",
            "unchanged",
        ):
            _require_nonnegative(getattr(self, name), f"SyncRun.{name}")
        if self.outcome not in {"success", "partial", "noop", "blocked", "failed"}:
            raise ValueError(f"Unsupported SyncRun outcome: {self.outcome}")
        if self.outcome == "success" and self.stored == 0 and self.published == 0:
            raise ValueError("A successful SyncRun must store or publish at least one item")
        if self.status is SyncRunStatus.BLOCKED and not self.error_code:
            raise ValueError("Blocked SyncRun requires an error_code")

    def finish(self, *, status: SyncRunStatus, outcome: str, finished_at: datetime) -> SyncRun:
        """Return a completed copy while preserving the original start time."""

        return SyncRun(
            run_id=self.run_id,
            dataset_key=self.dataset_key,
            trigger=self.trigger,
            status=status,
            outcome=outcome,
            requested=self.requested,
            fetched=self.fetched,
            validated=self.validated,
            quarantined=self.quarantined,
            succeeded=self.succeeded,
            failed=self.failed,
            stored=self.stored,
            published=self.published,
            unchanged=self.unchanged,
            provider_name=self.provider_name,
            contract_version=self.contract_version,
            config_snapshot_hash=self.config_snapshot_hash,
            started_at=self.started_at,
            finished_at=finished_at,
            error_code=self.error_code,
            error_message=self.error_message,
        )


@dataclass(frozen=True)
class SyncBatch:
    """Bounded provider/dataset slice within a sync run."""

    batch_id: str
    run_id: str
    dataset_key: str
    provider_name: str
    idempotency_key: str
    state: SyncItemState = SyncItemState.PENDING
    requested: int = 0
    fetched: int = 0
    validated: int = 0
    quarantined: int = 0
    succeeded: int = 0
    failed: int = 0
    stored: int = 0
    published: int = 0
    window_start: date | None = None
    window_end: date | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        for name in ("batch_id", "run_id", "dataset_key", "provider_name", "idempotency_key"):
            if not getattr(self, name).strip():
                raise ValueError(f"SyncBatch.{name} cannot be empty")
        if self.window_start and self.window_end and self.window_end < self.window_start:
            raise ValueError("SyncBatch.window_end cannot precede window_start")
        for name in (
            "requested",
            "fetched",
            "validated",
            "quarantined",
            "succeeded",
            "failed",
            "stored",
            "published",
        ):
            _require_nonnegative(getattr(self, name), f"SyncBatch.{name}")
        if self.started_at is not None:
            _require_aware(self.started_at, "SyncBatch.started_at")
        if self.finished_at is not None:
            _require_aware(self.finished_at, "SyncBatch.finished_at")
        if self.started_at and self.finished_at and self.finished_at < self.started_at:
            raise ValueError("SyncBatch.finished_at cannot precede started_at")


@dataclass(frozen=True)
class SyncCheckpoint:
    """Resumable cursor checkpoint for a bounded batch."""

    checkpoint_id: str
    run_id: str
    batch_id: str
    cursor_name: str
    cursor_value: str
    state: SyncItemState = SyncItemState.SUCCEEDED
    processed: int = 0
    failed: int = 0
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error_code: str = ""

    def __post_init__(self) -> None:
        for name in ("checkpoint_id", "run_id", "batch_id", "cursor_name", "cursor_value"):
            if not getattr(self, name).strip():
                raise ValueError(f"SyncCheckpoint.{name} cannot be empty")
        _require_aware(self.recorded_at, "SyncCheckpoint.recorded_at")
        _require_nonnegative(self.processed, "SyncCheckpoint.processed")
        _require_nonnegative(self.failed, "SyncCheckpoint.failed")
        if self.state is SyncItemState.FAILED and not self.error_code:
            raise ValueError("Failed SyncCheckpoint requires an error_code")


@dataclass(frozen=True)
class QuarantineRecord:
    """A payload or row that failed acceptance and must not be published."""

    quarantine_id: str
    dataset_key: str
    provider_name: str
    natural_key: str
    reason_code: str
    reason: str
    payload_hash: str
    schema_fingerprint: str
    payload: dict[str, Any]
    observed_at: datetime | None = None
    run_id: str = ""
    batch_id: str = ""
    resolution: QuarantineResolution = QuarantineResolution.OPEN
    quarantined_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolved_by: str = ""

    def __post_init__(self) -> None:
        for name in (
            "quarantine_id",
            "dataset_key",
            "provider_name",
            "natural_key",
            "reason_code",
            "reason",
            "payload_hash",
            "schema_fingerprint",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"QuarantineRecord.{name} cannot be empty")
        _require_aware(self.quarantined_at, "QuarantineRecord.quarantined_at")
        if self.observed_at is not None:
            _require_aware(self.observed_at, "QuarantineRecord.observed_at")
        if self.resolved_at is not None:
            _require_aware(self.resolved_at, "QuarantineRecord.resolved_at")
            if self.resolved_at < self.quarantined_at:
                raise ValueError("QuarantineRecord.resolved_at cannot precede quarantined_at")
        if self.resolution is not QuarantineResolution.OPEN and self.resolved_at is None:
            raise ValueError("Resolved quarantine records require resolved_at")


@dataclass(frozen=True)
class CoverageSnapshot:
    """Coverage and conflict evidence attached to a publication."""

    coverage_id: str
    publication_id: str
    requested_count: int
    eligible_count: int
    selected_count: int
    missing_count: int = 0
    conflict_count: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        for name in (
            "requested_count",
            "eligible_count",
            "selected_count",
            "missing_count",
            "conflict_count",
        ):
            _require_nonnegative(getattr(self, name), f"CoverageSnapshot.{name}")
        if self.selected_count > self.eligible_count:
            raise ValueError("selected_count cannot exceed eligible_count")
        if self.eligible_count > self.requested_count:
            raise ValueError("eligible_count cannot exceed requested_count")
        _require_aware(self.generated_at, "CoverageSnapshot.generated_at")

    @property
    def coverage_ratio(self) -> float:
        """Return selected/requested coverage, with empty scope failing closed."""

        if self.requested_count == 0:
            return 0.0
        return self.selected_count / self.requested_count


@dataclass(frozen=True)
class CanonicalPublication:
    """Versioned, auditable selection of canonical facts."""

    publication_id: str
    dataset_key: str
    publication_key: str
    policy_version: str
    state: PublicationState
    selected_source: str
    publication_hash: str
    coverage: CoverageSnapshot
    member_count: int = 0
    conflict_count: int = 0
    as_of: datetime | None = None
    published_at: datetime | None = None
    superseded_at: datetime | None = None
    must_not_use_for_decision: bool = False
    blocked_reason: str = ""
    created_by: str = "system"
    run_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "publication_id",
            "dataset_key",
            "publication_key",
            "policy_version",
            "publication_hash",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"CanonicalPublication.{name} cannot be empty")
        _require_nonnegative(self.member_count, "CanonicalPublication.member_count")
        _require_nonnegative(self.conflict_count, "CanonicalPublication.conflict_count")
        if self.as_of is not None:
            _require_aware(self.as_of, "CanonicalPublication.as_of")
        if self.published_at is not None:
            _require_aware(self.published_at, "CanonicalPublication.published_at")
        if self.superseded_at is not None:
            _require_aware(self.superseded_at, "CanonicalPublication.superseded_at")
        if self.state is PublicationState.PUBLISHED:
            if not self.selected_source:
                raise ValueError("Published publication requires selected_source")
            if self.published_at is None:
                raise ValueError("Published publication requires published_at")
            if self.must_not_use_for_decision:
                raise ValueError("Published publication cannot be blocked for decisions")
            if self.member_count == 0:
                raise ValueError("Published publication requires at least one member")
        if self.state is PublicationState.BLOCKED and not self.blocked_reason.strip():
            raise ValueError("Blocked publication requires blocked_reason")


@dataclass(frozen=True)
class PublicationMember:
    """One selected canonical fact in a publication."""

    member_id: str
    publication_id: str
    dataset_key: str
    natural_key: str
    source: str
    source_record_id: str
    fact_table: str
    fact_pk: str
    observed_at: datetime | None = None
    raw_payload_hash: str = ""
    quality_status: str = "accepted"
    revision_number: int = 1

    def __post_init__(self) -> None:
        for name in (
            "member_id",
            "publication_id",
            "dataset_key",
            "natural_key",
            "source",
            "source_record_id",
            "fact_table",
            "fact_pk",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"PublicationMember.{name} cannot be empty")
        if self.observed_at is not None:
            _require_aware(self.observed_at, "PublicationMember.observed_at")
        if self.revision_number < 1:
            raise ValueError("PublicationMember.revision_number must be positive")


__all__ = [
    "CanonicalPublication",
    "CoverageSnapshot",
    "PublicationMember",
    "PublicationFactReference",
    "PublicationState",
    "QuarantineRecord",
    "QuarantineResolution",
    "SyncBatch",
    "SyncCheckpoint",
    "SyncItemState",
    "SyncRun",
    "SyncRunStatus",
]
