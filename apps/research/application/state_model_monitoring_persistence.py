"""ID-only persistence and exact PIT query contracts for R6 monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessment,
    R6MonitoringAssessmentStatus,
    R6MonitoringObservation,
    R6MonitoringPeriodCalendar,
    R6MonitoringPolicy,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef


class R6MonitoringPersistenceConflict(RuntimeError):
    """An immutable monitoring identity has a different persisted winner."""


class R6MonitoringPersistenceCorruption(RuntimeError):
    """Persisted monitoring evidence failed strict canonical replay."""


class R6MonitoringPersistenceUnavailable(RuntimeError):
    """Exact owner evidence or a requested PIT cutoff is unavailable."""


def r6_monitoring_assessment_id(
    *,
    qualification_ref: R6QualificationRef,
    expected_policy_hash: str,
    evaluated_at: datetime,
) -> str:
    """Derive the unique ID-only command identity for one assessment cutoff."""

    if len(expected_policy_hash) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in expected_policy_hash
    ):
        raise ValueError("expected_policy_hash must be a SHA-256 digest")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")

    digest = sha256(
        (
            f"{qualification_ref.assessment_id}\x00"
            f"{qualification_ref.assessment_hash.lower()}\x00"
            f"{expected_policy_hash.lower()}\x00"
            f"{evaluated_at.astimezone(UTC).isoformat()}"
        ).encode()
    ).hexdigest()
    return f"r6-monitoring-assessment:{digest}"


@dataclass(frozen=True)
class R6MonitoringAssessmentRef:
    """Exact persisted assessment identity and canonical seal."""

    assessment_id: str
    assessment_hash: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.assessment_id, str)
            or not self.assessment_id.strip()
            or len(self.assessment_id) > 192
            or any(character.isspace() for character in self.assessment_id)
        ):
            raise ValueError("assessment_id must be a bounded non-blank token")
        if len(self.assessment_hash) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in self.assessment_hash
        ):
            raise ValueError("assessment_hash must be a SHA-256 digest")


@dataclass(frozen=True)
class RegisterR6MonitoringAssessmentCommand:
    """Identity/cutoff-only write command; no raw values are accepted."""

    qualification_ref: R6QualificationRef
    policy_id: str
    policy_version: str
    expected_policy_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        for value, label in (
            (self.policy_id, "policy_id"),
            (self.policy_version, "policy_version"),
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 192
                or any(character.isspace() for character in value)
            ):
                raise ValueError(f"{label} must be a bounded non-blank token")
        if len(self.expected_policy_hash) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in self.expected_policy_hash
        ):
            raise ValueError("expected_policy_hash must be a SHA-256 digest")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")


@dataclass(frozen=True)
class GetExactR6MonitoringAssessmentCommand:
    """Exact PIT query bound to immutable identity and hash."""

    assessment_ref: R6MonitoringAssessmentRef
    as_of: datetime

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")


@dataclass(frozen=True)
class R6MonitoringPersistedAssessment:
    """Strictly restored policy/calendar/raw-fact/assessment graph."""

    assessment_ref: R6MonitoringAssessmentRef
    policy: R6MonitoringPolicy
    period_calendar: R6MonitoringPeriodCalendar
    observations: tuple[R6MonitoringObservation, ...]
    assessment: R6MonitoringAssessment
    recorded_at: datetime


@dataclass(frozen=True)
class R6MonitoringAuditEntry:
    """Bounded internal audit projection; it grants no production authority."""

    assessment_ref: R6MonitoringAssessmentRef
    qualification_ref: R6QualificationRef
    policy_id: str
    policy_version: str
    evaluated_at: datetime
    recorded_at: datetime
    status: R6MonitoringAssessmentStatus
    observation_count: int
    blockers: tuple[str, ...]
    retirement_review_required: bool


@dataclass(frozen=True)
class R6MonitoringAuditPage:
    """Deterministic PIT page of internal monitoring assessments."""

    entries: tuple[R6MonitoringAuditEntry, ...]
    next_cursor: str | None


class R6MonitoringAssessmentWriter(Protocol):
    """Closure-bound append capability for ID-only recomputation."""

    def register(
        self,
        command: RegisterR6MonitoringAssessmentCommand,
    ) -> R6MonitoringPersistedAssessment:
        """Exact-reread, recompute, and append one immutable graph."""


class R6MonitoringAssessmentRepository(Protocol):
    """Read-only exact PIT and audit boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary identity."""

    def get_exact(
        self,
        *,
        assessment_ref: R6MonitoringAssessmentRef,
        as_of: datetime,
    ) -> R6MonitoringPersistedAssessment | None:
        """Return one exact graph knowable at ``as_of`` or absence."""

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R6MonitoringAuditPage:
        """Return a deterministic bounded internal audit page."""


class RegisterR6MonitoringAssessment:
    """Application facade retaining writes behind a composition closure."""

    def __init__(self, writer: R6MonitoringAssessmentWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: RegisterR6MonitoringAssessmentCommand,
    ) -> R6MonitoringPersistedAssessment:
        """Register one locally recomputed monitoring graph."""

        return self._writer.register(command)


class GetExactR6MonitoringAssessment:
    """Application facade for exact PIT reads only."""

    def __init__(self, repository: R6MonitoringAssessmentRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR6MonitoringAssessmentCommand,
    ) -> R6MonitoringPersistedAssessment | None:
        """Return one exact persisted graph or explicit absence."""

        return self._repository.get_exact(
            assessment_ref=command.assessment_ref,
            as_of=command.as_of,
        )


class AuditR6MonitoringAssessments:
    """Read-only bounded internal monitoring audit facade."""

    def __init__(self, repository: R6MonitoringAssessmentRepository) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        as_of: datetime,
        cursor: str | None = None,
        limit: int = 50,
    ) -> R6MonitoringAuditPage:
        """Return a PIT page without latest/current semantics."""

        if isinstance(limit, bool) or limit < 1 or limit > 200:
            raise ValueError("R6 monitoring audit limit must be between 1 and 200")
        return self._repository.list_audit(as_of=as_of, cursor=cursor, limit=limit)


__all__ = [
    "AuditR6MonitoringAssessments",
    "GetExactR6MonitoringAssessment",
    "GetExactR6MonitoringAssessmentCommand",
    "R6MonitoringAssessmentRef",
    "R6MonitoringAssessmentRepository",
    "R6MonitoringAssessmentWriter",
    "R6MonitoringAuditEntry",
    "R6MonitoringAuditPage",
    "R6MonitoringPersistedAssessment",
    "R6MonitoringPersistenceConflict",
    "R6MonitoringPersistenceCorruption",
    "R6MonitoringPersistenceUnavailable",
    "RegisterR6MonitoringAssessment",
    "RegisterR6MonitoringAssessmentCommand",
    "r6_monitoring_assessment_id",
]
