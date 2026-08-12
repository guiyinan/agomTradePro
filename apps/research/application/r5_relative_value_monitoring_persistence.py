"""Persistence and exact PIT contracts for R5 post-promotion monitoring."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.application.r5_relative_value_monitoring import (
    EvaluateR5PostPromotionMonitoringCommand,
    R5MonitoringEvaluationEvidence,
    R5PostPromotionMonitoringUnavailable,
)
from apps.research.domain.r5_relative_value_monitoring import (
    R5MonitoringAssessmentStatus,
    R5PostPromotionMonitoringAssessment,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringCalendar,
    R5MonitoringFixedIncomeEvidence,
    R5MonitoringPolicy,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5PostPromotionMonitoringFact,
)


class R5MonitoringPersistenceConflict(RuntimeError):
    """An immutable command or period identity has another winner."""


class R5MonitoringPersistenceCorruption(RuntimeError):
    """Persisted monitoring evidence failed strict reconstruction or replay."""


class R5MonitoringPersistenceUnavailable(RuntimeError):
    """A trusted owner, clock, cutoff, or write capability is unavailable."""


@dataclass(frozen=True)
class R5MonitoringAssessmentRef:
    """Exact persisted assessment identity and canonical content seal."""

    assessment_id: str
    assessment_hash: str

    def __post_init__(self) -> None:
        _require_token(self.assessment_id, "R5 monitoring assessment_id")
        _require_hash(self.assessment_hash, "R5 monitoring assessment_hash")


@dataclass(frozen=True)
class GetExactR5MonitoringAssessmentCommand:
    """Exact PIT read accepting no latest or current semantics."""

    assessment_ref: R5MonitoringAssessmentRef
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.assessment_ref) is not R5MonitoringAssessmentRef:
            raise TypeError("R5 monitoring assessment_ref is invalid")
        R5MonitoringAssessmentRef.__post_init__(self.assessment_ref)
        _require_aware(self.as_of, "R5 monitoring exact as_of")


@dataclass(frozen=True)
class AuditR5MonitoringAssessmentsCommand:
    """Bounded internal-audit query with a snapshot-bound PIT cutoff."""

    as_of: datetime
    cursor: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "R5 monitoring audit as_of")
        if self.cursor is not None and (
            type(self.cursor) is not str or not self.cursor or len(self.cursor) > 4096
        ):
            raise ValueError("R5 monitoring audit cursor is invalid")
        if type(self.limit) is not int or not 1 <= self.limit <= 200:
            raise ValueError("R5 monitoring audit limit must be between 1 and 200")


@dataclass(frozen=True)
class R5MonitoringPersistedAssessment:
    """Strictly restored complete owner graph and local assessment."""

    assessment_ref: R5MonitoringAssessmentRef
    active_lifecycle: R5MonitoringActiveLifecycle
    fixed_income: R5MonitoringFixedIncomeEvidence
    policy: R5MonitoringPolicy
    calendar: R5MonitoringCalendar
    portfolio_facts: tuple[R5PostPromotionMonitoringFact, ...]
    assessment: R5PostPromotionMonitoringAssessment
    ledger_recorded_at: datetime


@dataclass(frozen=True)
class R5MonitoringAuditEntry:
    """Research-only immutable audit projection."""

    assessment_ref: R5MonitoringAssessmentRef
    result_id: str
    result_hash: str
    policy_id: str
    policy_version: str
    evaluated_at: datetime
    ledger_recorded_at: datetime
    status: R5MonitoringAssessmentStatus
    fact_count: int
    blocker_codes: tuple[str, ...]
    retirement_review_required: bool


@dataclass(frozen=True)
class R5MonitoringAuditPage:
    """One immutable-snapshot page of monitoring assessments."""

    entries: tuple[R5MonitoringAuditEntry, ...]
    next_cursor: str | None
    as_of: datetime


class R5MonitoringEvidenceEvaluator(Protocol):
    """Phase A exact owner-reread boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner transaction identity."""

    def execute_evidence(
        self,
        command: EvaluateR5PostPromotionMonitoringCommand,
    ) -> R5MonitoringEvaluationEvidence:
        """Reread every owner and recompute the complete assessment."""


class R5MonitoringAssessmentWriter(Protocol):
    """Private append capability retained outside public runtime graphs."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the exact transaction shared by owner reads."""

    def append_evidence(
        self,
        *,
        command: EvaluateR5PostPromotionMonitoringCommand,
        evidence: R5MonitoringEvaluationEvidence,
    ) -> R5MonitoringPersistedAssessment:
        """Append one exact replay of the complete owner graph."""


class R5MonitoringAssessmentRepository(Protocol):
    """Public read-only exact PIT and internal-audit boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

    def get_exact(
        self,
        *,
        assessment_ref: R5MonitoringAssessmentRef,
        as_of: datetime,
    ) -> R5MonitoringPersistedAssessment | None:
        """Return one exact graph knowable at the cutoff or explicit absence."""

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R5MonitoringAuditPage:
        """Return one immutable-snapshot audit page."""


class RegisterR5MonitoringAssessment:
    """Evaluate and append only within the owners' shared database UoW."""

    def __init__(
        self,
        *,
        evaluator: R5MonitoringEvidenceEvaluator,
        writer: R5MonitoringAssessmentWriter,
    ) -> None:
        self._evaluator = evaluator
        self._writer = writer
        try:
            evaluator_key = _unit_of_work_key(evaluator.unit_of_work_key)
            writer_key = _unit_of_work_key(writer.unit_of_work_key)
        except Exception as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring unit of work is unavailable"
            ) from error
        if evaluator_key != writer_key:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring owners use different units of work"
            )
        self._expected_uow_key = evaluator_key

    def execute(
        self,
        command: EvaluateR5PostPromotionMonitoringCommand,
    ) -> R5MonitoringPersistedAssessment:
        """Persist a complete owner graph without lifecycle side effects."""

        _require_registration_command(command)
        self._require_unchanged_uow()
        try:
            with self._writer.atomic():
                self._require_unchanged_uow()
                evidence = self._evaluator.execute_evidence(command)
                self._require_unchanged_uow()
                _require_complete_evidence(evidence)
                persisted = self._writer.append_evidence(command=command, evidence=evidence)
                self._require_unchanged_uow()
                return persisted
        except (
            R5MonitoringPersistenceConflict,
            R5MonitoringPersistenceCorruption,
            R5MonitoringPersistenceUnavailable,
        ):
            raise
        except R5PostPromotionMonitoringUnavailable as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring owner graph is unavailable"
            ) from error
        except Exception as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring registration is unavailable"
            ) from error

    def _require_unchanged_uow(self) -> None:
        try:
            evaluator_key = _unit_of_work_key(self._evaluator.unit_of_work_key)
            writer_key = _unit_of_work_key(self._writer.unit_of_work_key)
        except Exception as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring unit of work is unavailable"
            ) from error
        if evaluator_key != self._expected_uow_key or writer_key != self._expected_uow_key:
            raise R5MonitoringPersistenceUnavailable("R5 monitoring unit of work identity changed")


class GetExactR5MonitoringAssessment:
    """Read-only exact PIT facade."""

    def __init__(self, repository: R5MonitoringAssessmentRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR5MonitoringAssessmentCommand,
    ) -> R5MonitoringPersistedAssessment | None:
        """Return one exact persisted graph or explicit absence."""

        _require_exact_command(command)
        return self._repository.get_exact(
            assessment_ref=command.assessment_ref,
            as_of=command.as_of,
        )


class AuditR5MonitoringAssessments:
    """Read-only bounded internal-audit facade."""

    def __init__(self, repository: R5MonitoringAssessmentRepository) -> None:
        self._repository = repository

    def execute(self, command: AuditR5MonitoringAssessmentsCommand) -> R5MonitoringAuditPage:
        """Return one cursor-bound immutable audit page."""

        _require_audit_command(command)
        return self._repository.list_audit(
            as_of=command.as_of,
            cursor=command.cursor,
            limit=command.limit,
        )


def _require_complete_evidence(evidence: R5MonitoringEvaluationEvidence) -> None:
    if type(evidence) is not R5MonitoringEvaluationEvidence:
        raise R5MonitoringPersistenceUnavailable("R5 monitoring owner graph type is invalid")
    if (
        evidence.policy is None
        or evidence.active_lifecycle is None
        or evidence.calendar is None
        or evidence.fixed_income is None
        or not evidence.portfolio_facts
    ):
        raise R5MonitoringPersistenceUnavailable(
            "complete R5 monitoring owner graph is unavailable"
        )
    try:
        validated = evidence.assessment.validated_copy(
            policy=evidence.policy,
            calendar=evidence.calendar,
            facts=evidence.portfolio_facts,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise R5MonitoringPersistenceUnavailable(
            "R5 monitoring assessment replay is unavailable"
        ) from error
    if validated != evidence.assessment:
        raise R5MonitoringPersistenceUnavailable("R5 monitoring assessment differs after replay")


def _require_registration_command(command: EvaluateR5PostPromotionMonitoringCommand) -> None:
    try:
        if type(command) is not EvaluateR5PostPromotionMonitoringCommand:
            raise TypeError("registration command type differs")
        EvaluateR5PostPromotionMonitoringCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise R5MonitoringPersistenceUnavailable(
            "R5 monitoring registration command is malformed"
        ) from error


def _require_exact_command(command: GetExactR5MonitoringAssessmentCommand) -> None:
    try:
        if type(command) is not GetExactR5MonitoringAssessmentCommand:
            raise TypeError("exact query command type differs")
        GetExactR5MonitoringAssessmentCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise R5MonitoringPersistenceUnavailable(
            "R5 monitoring exact query is malformed"
        ) from error


def _require_audit_command(command: AuditR5MonitoringAssessmentsCommand) -> None:
    try:
        if type(command) is not AuditR5MonitoringAssessmentsCommand:
            raise TypeError("audit command type differs")
        AuditR5MonitoringAssessmentsCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise R5MonitoringPersistenceUnavailable(
            "R5 monitoring audit query is malformed"
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
        raise ValueError(f"{label} must be lowercase sha256")


def _require_aware(value: object, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _unit_of_work_key(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError("unit_of_work_key must be an exact non-blank string")
    return value


__all__ = [
    "AuditR5MonitoringAssessments",
    "AuditR5MonitoringAssessmentsCommand",
    "GetExactR5MonitoringAssessment",
    "GetExactR5MonitoringAssessmentCommand",
    "R5MonitoringAssessmentRef",
    "R5MonitoringAssessmentRepository",
    "R5MonitoringAssessmentWriter",
    "R5MonitoringAuditEntry",
    "R5MonitoringAuditPage",
    "R5MonitoringPersistedAssessment",
    "R5MonitoringPersistenceConflict",
    "R5MonitoringPersistenceCorruption",
    "R5MonitoringPersistenceUnavailable",
    "RegisterR5MonitoringAssessment",
]
