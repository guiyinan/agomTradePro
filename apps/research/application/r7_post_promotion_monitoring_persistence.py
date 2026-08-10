"""Append-only persistence contracts for R7 post-promotion monitoring."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from apps.research.application.r7_post_promotion_monitoring import (
    EvaluateR7PostPromotionMonitoringCommand,
    R7MonitoringEvaluationEvidence,
    R7PostPromotionMonitoringUnavailable,
)
from apps.research.domain.r7_post_promotion_monitoring import R7MonitoringStatus


class R7MonitoringPersistenceUnavailable(RuntimeError):
    """An owner, shared UoW, clock, cutoff, or write capability is unavailable."""


class R7MonitoringPersistenceConflict(RuntimeError):
    """An immutable registration identity has conflicting evidence."""


class R7MonitoringPersistenceCorruption(RuntimeError):
    """Persisted monitoring evidence failed strict reconstruction or replay."""


def derive_r7_monitoring_assessment_id(
    command: EvaluateR7PostPromotionMonitoringCommand,
) -> str:
    """Derive one immutable ledger identity from the ID-only command."""

    _require_registration_command(command)
    digest = sha256(
        (
            f"{command.policy_id}\x00{command.policy_version}\x00"
            f"{command.expected_policy_hash}\x00"
            f"{command.as_of.astimezone(UTC).isoformat()}"
        ).encode()
    ).hexdigest()
    return f"r7-monitoring-assessment-ledger:{digest}"


def r7_monitoring_evidence_hash(evidence: R7MonitoringEvaluationEvidence) -> str:
    """Seal every canonical owner source and the locally derived assessment."""

    copied = evidence.validated_copy()
    values = (
        "r7-post-promotion-monitoring-evidence.v1",
        copied.policy.content_hash,
        copied.active_owner_graph.result.content_hash,
        *(event.content_hash for event in copied.active_owner_graph.lifecycle_stream),
        copied.active_owner_graph.lifecycle_owner_evidence.content_hash,
        copied.active.content_hash,
        copied.calendar.content_hash,
        copied.period.content_hash,
        copied.realization_owner_record.content_hash,
        copied.realization.content_hash,
        copied.assessment.content_hash,
    )
    return sha256("\x00".join(values).encode()).hexdigest()


@dataclass(frozen=True)
class R7MonitoringAssessmentRef:
    """Exact immutable ledger identity and complete evidence seal."""

    assessment_id: str
    assessment_version: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.assessment_id, "R7 monitoring assessment_id")
        _require_token(self.assessment_version, "R7 monitoring assessment_version")
        _require_hash(self.content_hash, "R7 monitoring assessment content_hash")


@dataclass(frozen=True)
class R7PersistedMonitoringAssessment:
    """Strictly reconstructed full evidence and trusted ledger timestamp."""

    reference: R7MonitoringAssessmentRef
    evidence: R7MonitoringEvaluationEvidence
    ledger_recorded_at: datetime

    def __post_init__(self) -> None:
        if type(self.reference) is not R7MonitoringAssessmentRef:
            raise TypeError("R7 monitoring persisted reference is invalid")
        self.reference.__post_init__()
        if type(self.evidence) is not R7MonitoringEvaluationEvidence:
            raise TypeError("R7 monitoring persisted evidence is invalid")
        self.evidence.validated_copy()
        _require_aware(self.ledger_recorded_at, "R7 monitoring ledger_recorded_at")
        if self.evidence.assessment.evaluated_at > self.ledger_recorded_at:
            raise ValueError("R7 monitoring ledger predates its assessment")
        if self.reference.content_hash != r7_monitoring_evidence_hash(self.evidence):
            raise ValueError("R7 monitoring persisted evidence hash mismatch")


@dataclass(frozen=True)
class GetExactR7MonitoringAssessmentCommand:
    """Exact PIT read with no latest/current semantics."""

    reference: R7MonitoringAssessmentRef
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.reference) is not R7MonitoringAssessmentRef:
            raise TypeError("R7 monitoring exact reference is invalid")
        self.reference.__post_init__()
        _require_aware(self.as_of, "R7 monitoring exact as_of")


@dataclass(frozen=True)
class AuditR7MonitoringAssessmentsCommand:
    """Bounded internal-audit query pinned to an immutable PIT snapshot."""

    as_of: datetime
    cursor: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "R7 monitoring audit as_of")
        if self.cursor is not None and (
            type(self.cursor) is not str or not self.cursor or len(self.cursor) > 4096
        ):
            raise ValueError("R7 monitoring audit cursor is invalid")
        if type(self.limit) is not int or not 1 <= self.limit <= 200:
            raise ValueError("R7 monitoring audit limit must be between 1 and 200")


@dataclass(frozen=True)
class R7MonitoringAuditEntry:
    """Research-only audit projection carrying no retirement authority."""

    reference: R7MonitoringAssessmentRef
    policy_id: str
    policy_version: str
    result_id: str
    result_hash: str
    period_id: str
    evaluated_at: datetime
    ledger_recorded_at: datetime
    status: R7MonitoringStatus
    observation_count: int
    blocker_codes: tuple[str, ...]
    manual_retirement_review_required: bool


@dataclass(frozen=True)
class R7MonitoringAuditPage:
    """One stable page from an immutable signed audit snapshot."""

    entries: tuple[R7MonitoringAuditEntry, ...]
    next_cursor: str | None
    as_of: datetime


class R7MonitoringEvidenceEvaluator(Protocol):
    """Phase A exact owner-reread boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database/snapshot identity."""

    def execute_evidence(
        self,
        command: EvaluateR7PostPromotionMonitoringCommand,
    ) -> R7MonitoringEvaluationEvidence:
        """Reread and locally derive one complete owner graph."""


class R7MonitoringAssessmentWriter(Protocol):
    """Private append capability retained outside public runtime graphs."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the transaction shared by owner reads and append."""

    def append_evidence(
        self,
        *,
        command: EvaluateR7PostPromotionMonitoringCommand,
        evidence: R7MonitoringEvaluationEvidence,
    ) -> R7MonitoringEvaluationEvidence:
        """Append or exact-replay one complete assessment graph."""


class R7MonitoringReadRepository(Protocol):
    """Read-only exact PIT and immutable-audit boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

    def get_exact(
        self,
        *,
        reference: R7MonitoringAssessmentRef,
        as_of: datetime,
    ) -> R7PersistedMonitoringAssessment | None:
        """Return one exact receipt known at the PIT cutoff."""

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R7MonitoringAuditPage:
        """Return one immutable-snapshot audit page."""


class RegisterR7MonitoringAssessment:
    """Re-evidence all owners immediately before an append-only registration."""

    def __init__(
        self,
        *,
        evaluator: R7MonitoringEvidenceEvaluator,
        writer: R7MonitoringAssessmentWriter,
    ) -> None:
        self._evaluator = evaluator
        self._writer = writer
        self._expected_uow_key = _require_shared_uow(evaluator, writer)

    def execute(
        self,
        command: EvaluateR7PostPromotionMonitoringCommand,
    ) -> R7MonitoringEvaluationEvidence:
        """Append only after two matching complete evaluations in one UoW."""

        _require_registration_command(command)
        self._require_unchanged_uow()
        try:
            with self._writer.atomic():
                self._require_unchanged_uow()
                evidence = self._evaluator.execute_evidence(command).validated_copy()
                self._require_unchanged_uow()
                reread = self._evaluator.execute_evidence(command).validated_copy()
                if evidence != reread:
                    raise R7MonitoringPersistenceUnavailable(
                        "R7 monitoring owner evidence changed during registration"
                    )
                self._require_unchanged_uow()
                persisted = self._writer.append_evidence(
                    command=command,
                    evidence=reread,
                )
                self._require_unchanged_uow()
                return persisted.validated_copy()
        except (
            R7MonitoringPersistenceConflict,
            R7MonitoringPersistenceCorruption,
            R7MonitoringPersistenceUnavailable,
        ):
            raise
        except R7PostPromotionMonitoringUnavailable as error:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring owner graph is unavailable"
            ) from error
        except Exception as error:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring registration is unavailable"
            ) from error

    def _require_unchanged_uow(self) -> None:
        if _require_shared_uow(self._evaluator, self._writer) != self._expected_uow_key:
            raise R7MonitoringPersistenceUnavailable("R7 monitoring unit of work identity changed")


class GetExactR7MonitoringAssessment:
    """Read-only exact PIT facade."""

    def __init__(self, repository: R7MonitoringReadRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR7MonitoringAssessmentCommand,
    ) -> R7PersistedMonitoringAssessment | None:
        """Return one exact persisted graph or explicit absence."""

        _require_exact_command(command)
        return self._repository.get_exact(
            reference=command.reference,
            as_of=command.as_of,
        )


class AuditR7MonitoringAssessments:
    """Read-only bounded internal-audit facade."""

    def __init__(self, repository: R7MonitoringReadRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: AuditR7MonitoringAssessmentsCommand,
    ) -> R7MonitoringAuditPage:
        """Return one signed cursor-bound immutable audit page."""

        _require_audit_command(command)
        return self._repository.list_audit(
            as_of=command.as_of,
            cursor=command.cursor,
            limit=command.limit,
        )


def _require_shared_uow(
    evaluator: R7MonitoringEvidenceEvaluator,
    writer: R7MonitoringAssessmentWriter,
) -> str:
    try:
        evaluator_key = _unit_of_work_key(evaluator.unit_of_work_key)
        writer_key = _unit_of_work_key(writer.unit_of_work_key)
    except Exception as error:
        raise R7MonitoringPersistenceUnavailable(
            "R7 monitoring unit of work is unavailable"
        ) from error
    if evaluator_key != writer_key:
        raise R7MonitoringPersistenceUnavailable("R7 monitoring owners use different units of work")
    return evaluator_key


def _require_registration_command(
    command: EvaluateR7PostPromotionMonitoringCommand,
) -> None:
    try:
        if type(command) is not EvaluateR7PostPromotionMonitoringCommand:
            raise TypeError("registration command type differs")
        command.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise R7MonitoringPersistenceUnavailable(
            "R7 monitoring registration command is malformed"
        ) from error


def _require_exact_command(command: GetExactR7MonitoringAssessmentCommand) -> None:
    try:
        if type(command) is not GetExactR7MonitoringAssessmentCommand:
            raise TypeError("exact query command type differs")
        command.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise R7MonitoringPersistenceUnavailable(
            "R7 monitoring exact query is malformed"
        ) from error


def _require_audit_command(command: AuditR7MonitoringAssessmentsCommand) -> None:
    try:
        if type(command) is not AuditR7MonitoringAssessmentsCommand:
            raise TypeError("audit query command type differs")
        command.__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise R7MonitoringPersistenceUnavailable(
            "R7 monitoring audit query is malformed"
        ) from error


def _require_token(value: object, label: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 300
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be an exact bounded token")


def _require_hash(value: object, label: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be lowercase SHA-256")


def _require_aware(value: object, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _unit_of_work_key(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 192:
        raise TypeError("unit_of_work_key must be an exact non-blank string")
    return value


__all__ = [
    "AuditR7MonitoringAssessments",
    "AuditR7MonitoringAssessmentsCommand",
    "GetExactR7MonitoringAssessment",
    "GetExactR7MonitoringAssessmentCommand",
    "R7MonitoringAssessmentRef",
    "R7MonitoringAssessmentWriter",
    "R7MonitoringAuditEntry",
    "R7MonitoringAuditPage",
    "R7MonitoringPersistenceConflict",
    "R7MonitoringPersistenceCorruption",
    "R7MonitoringPersistenceUnavailable",
    "R7MonitoringReadRepository",
    "R7PersistedMonitoringAssessment",
    "RegisterR7MonitoringAssessment",
    "derive_r7_monitoring_assessment_id",
    "r7_monitoring_evidence_hash",
]
