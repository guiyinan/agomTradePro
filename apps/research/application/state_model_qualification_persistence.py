"""ID-only persistence contracts for R6 qualification evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from apps.research.domain.state_model_qualification import (
    StateModelQualificationAssessment,
)
from apps.research.domain.state_model_qualification_contracts import (
    StateModelQualificationStatus,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef


class R6QualificationConflict(RuntimeError):
    """A duplicate immutable R6 identity conflicts with an existing row."""


class R6QualificationCorruption(RuntimeError):
    """Persisted R6 evidence failed a canonical or relational invariant."""


class R6QualificationUnavailable(RuntimeError):
    """An exact R6 evidence item is absent or outside the PIT cutoff."""


def r6_qualification_assessment_id(
    *,
    study_id: str,
    assessed_at: datetime,
    content_hash: str,
) -> str:
    """Derive a stable identity from the exact study/cutoff/seal tuple."""

    digest = sha256(
        f"{study_id}\x00{assessed_at.astimezone(UTC).isoformat()}\x00{content_hash}".encode()
    ).hexdigest()
    return f"r6-qualification-assessment:{digest}"


@dataclass(frozen=True)
class RegisterR6QualificationAssessmentCommand:
    """ID/cutoff-only request; owner evidence is never caller-supplied."""

    study_id: str
    assessed_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.study_id, str)
            or not self.study_id.strip()
            or len(self.study_id) > 192
            or any(character.isspace() for character in self.study_id)
        ):
            raise ValueError("study_id must be a bounded non-blank token")
        if self.assessed_at.tzinfo is None or self.assessed_at.utcoffset() is None:
            raise ValueError("assessed_at must be timezone-aware")


@dataclass(frozen=True)
class GetExactR6QualificationAssessmentCommand:
    """Exact PIT assessment query bound to identity and content hash."""

    assessment_ref: R6QualificationRef
    as_of: datetime

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")


@dataclass(frozen=True)
class R6QualificationAuditEntry:
    """One immutable assessment plus its currently derived lifecycle state."""

    assessment_ref: R6QualificationRef
    study_id: str
    status: StateModelQualificationStatus
    assessed_at: datetime
    recorded_at: datetime
    blockers: tuple[str, ...]
    active: bool
    head_event_hash: str | None


@dataclass(frozen=True)
class R6QualificationAuditPage:
    """Stable cursor page for internal audit/monitoring consumers."""

    entries: tuple[R6QualificationAuditEntry, ...]
    next_cursor: str | None


class R6QualificationAssessmentWriter(Protocol):
    """Closure-bound append capability for one ID-only command."""

    def register(
        self,
        command: RegisterR6QualificationAssessmentCommand,
    ) -> StateModelQualificationAssessment:
        """Recompute exact owner evidence and append one server-clocked result."""


class R6QualificationExactReadRepository(Protocol):
    """Narrow read-only boundary for one exact PIT assessment."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def get_exact(
        self,
        *,
        assessment_ref: R6QualificationRef,
        as_of: datetime,
    ) -> StateModelQualificationAssessment | None:
        """Return one exact persisted assessment knowable at ``as_of``."""


class R6QualificationAssessmentRepository(R6QualificationExactReadRepository, Protocol):
    """Read-only exact PIT and internal audit page boundary."""

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R6QualificationAuditPage:
        """Return a bounded deterministic page without latest/current fallback."""


class RegisterR6QualificationAssessment:
    """Application facade for server-clocked R6 qualification persistence."""

    def __init__(self, writer: R6QualificationAssessmentWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: RegisterR6QualificationAssessmentCommand,
    ) -> StateModelQualificationAssessment:
        """Register one exact assessment through the closure-bound writer."""

        return self._writer.register(command)


class GetExactR6QualificationAssessment:
    """Application facade for one exact PIT assessment query."""

    def __init__(self, repository: R6QualificationExactReadRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR6QualificationAssessmentCommand,
    ) -> StateModelQualificationAssessment | None:
        """Return the persisted assessment or explicit absence."""

        return self._repository.get_exact(
            assessment_ref=command.assessment_ref,
            as_of=command.as_of,
        )


class MonitorR6Qualification:
    """Read-only bounded audit/monitoring facade."""

    def __init__(self, repository: R6QualificationAssessmentRepository) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        as_of: datetime,
        cursor: str | None = None,
        limit: int = 50,
    ) -> R6QualificationAuditPage:
        """Return a deterministic page; invalid limits/cursors fail closed."""

        if isinstance(limit, bool) or limit < 1 or limit > 200:
            raise ValueError("R6 qualification audit limit must be between 1 and 200")
        return self._repository.list_audit(as_of=as_of, cursor=cursor, limit=limit)


__all__ = [
    "R6QualificationConflict",
    "R6QualificationCorruption",
    "R6QualificationExactReadRepository",
    "R6QualificationUnavailable",
    "GetExactR6QualificationAssessment",
    "GetExactR6QualificationAssessmentCommand",
    "MonitorR6Qualification",
    "R6QualificationAssessmentRepository",
    "R6QualificationAssessmentWriter",
    "R6QualificationAuditEntry",
    "R6QualificationAuditPage",
    "RegisterR6QualificationAssessment",
    "RegisterR6QualificationAssessmentCommand",
    "r6_qualification_assessment_id",
]
