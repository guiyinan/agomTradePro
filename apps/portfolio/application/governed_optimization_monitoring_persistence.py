"""Persistence and exact PIT contracts for governed optimization monitoring."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.application.governed_optimization_monitoring import (
    EvaluateGovernedOptimizationMonitoringCommand,
    GovernedOptimizationMonitoringEvaluationEvidence,
    GovernedOptimizationMonitoringUnavailable,
)
from apps.portfolio.domain._optimization_canonical import (
    require_aware,
    require_sha256,
    require_token,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.governed_optimization_monitoring import (
    ActiveGovernedOptimizationResultEvidence,
    GovernedOptimizationMonitoringAssessment,
    GovernedOptimizationMonitoringCalendar,
    GovernedOptimizationMonitoringPolicy,
    MonitoringAssessmentStatus,
    OptimizationMonitoringPeriodObservation,
    OptimizationMonitoringSourceEvidence,
)
from apps.portfolio.domain.optimization_input_receipt import (
    GovernedOptimizationInputReceipt,
)


class GovernedOptimizationMonitoringPersistenceConflict(RuntimeError):
    """An immutable command or observation identity has another winner."""


class GovernedOptimizationMonitoringPersistenceCorruption(RuntimeError):
    """Persisted monitoring evidence failed strict replay."""


class GovernedOptimizationMonitoringPersistenceUnavailable(RuntimeError):
    """A trusted owner, clock, cutoff, or write capability is unavailable."""


@dataclass(frozen=True)
class GovernedOptimizationMonitoringAssessmentRef:
    """Exact persisted assessment identity and canonical content seal."""

    assessment_id: str
    assessment_hash: str

    def __post_init__(self) -> None:
        require_token(self.assessment_id, "monitoring assessment_id")
        require_sha256(self.assessment_hash, "monitoring assessment_hash")


@dataclass(frozen=True)
class GetExactGovernedOptimizationMonitoringAssessmentCommand:
    """Exact PIT read accepting no latest/current semantics."""

    assessment_ref: GovernedOptimizationMonitoringAssessmentRef
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.assessment_ref) is not GovernedOptimizationMonitoringAssessmentRef:
            raise TypeError("monitoring assessment_ref is invalid")
        GovernedOptimizationMonitoringAssessmentRef.__post_init__(self.assessment_ref)
        require_aware(self.as_of, "monitoring exact as_of")


@dataclass(frozen=True)
class AuditGovernedOptimizationMonitoringAssessmentsCommand:
    """Bounded internal audit query with a cursor-bound PIT cutoff."""

    as_of: datetime
    cursor: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        require_aware(self.as_of, "monitoring audit as_of")
        if self.cursor is not None and (
            type(self.cursor) is not str or not self.cursor or len(self.cursor) > 4096
        ):
            raise ValueError("monitoring audit cursor is invalid")
        if type(self.limit) is not int or not 1 <= self.limit <= 200:
            raise ValueError("monitoring audit limit must be between 1 and 200")


@dataclass(frozen=True)
class GovernedOptimizationMonitoringPersistedAssessment:
    """Strictly restored complete owner graph and local assessment."""

    assessment_ref: GovernedOptimizationMonitoringAssessmentRef
    active_result: ActiveGovernedOptimizationResultEvidence
    receipt: GovernedOptimizationInputReceipt
    upstream_promotions: tuple[ExactPromotionAttestation, ...]
    policy: GovernedOptimizationMonitoringPolicy
    calendar: GovernedOptimizationMonitoringCalendar
    portfolio_evidence: tuple[OptimizationMonitoringSourceEvidence, ...]
    broker_evidence: tuple[OptimizationMonitoringSourceEvidence, ...]
    observations: tuple[OptimizationMonitoringPeriodObservation, ...]
    assessment: GovernedOptimizationMonitoringAssessment
    ledger_recorded_at: datetime


@dataclass(frozen=True)
class GovernedOptimizationMonitoringAuditEntry:
    """Research-only immutable audit projection."""

    assessment_ref: GovernedOptimizationMonitoringAssessmentRef
    result_id: str
    result_hash: str
    policy_id: str
    policy_version: str
    evaluated_at: datetime
    ledger_recorded_at: datetime
    status: MonitoringAssessmentStatus
    observation_count: int
    blocker_codes: tuple[str, ...]
    retirement_review_required: bool


@dataclass(frozen=True)
class GovernedOptimizationMonitoringAuditPage:
    """One immutable-snapshot page of monitoring assessments."""

    entries: tuple[GovernedOptimizationMonitoringAuditEntry, ...]
    next_cursor: str | None
    as_of: datetime


class GovernedOptimizationMonitoringEvidenceEvaluator(Protocol):
    """Phase A exact owner reread boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner transaction identity."""

    def execute_evidence(
        self,
        command: EvaluateGovernedOptimizationMonitoringCommand,
    ) -> GovernedOptimizationMonitoringEvaluationEvidence:
        """Reread every owner and recompute the complete assessment."""


class GovernedOptimizationMonitoringAssessmentWriter(Protocol):
    """Private append capability retained outside public runtime graphs."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the exact transaction shared by owner reads."""

    def append_evidence(
        self,
        *,
        command: EvaluateGovernedOptimizationMonitoringCommand,
        evidence: GovernedOptimizationMonitoringEvaluationEvidence,
    ) -> GovernedOptimizationMonitoringPersistedAssessment:
        """Append one exact replay of the complete graph."""


class GovernedOptimizationMonitoringAssessmentRepository(Protocol):
    """Public read-only exact PIT and internal-audit boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

    def get_exact(
        self,
        *,
        assessment_ref: GovernedOptimizationMonitoringAssessmentRef,
        as_of: datetime,
    ) -> GovernedOptimizationMonitoringPersistedAssessment | None:
        """Return one exact graph knowable at the cutoff or absence."""

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> GovernedOptimizationMonitoringAuditPage:
        """Return one immutable-snapshot audit page."""


class RegisterGovernedOptimizationMonitoringAssessment:
    """Evaluate and append only within the owners' shared database UoW."""

    def __init__(
        self,
        *,
        evaluator: GovernedOptimizationMonitoringEvidenceEvaluator,
        writer: GovernedOptimizationMonitoringAssessmentWriter,
    ) -> None:
        self._evaluator = evaluator
        self._writer = writer
        try:
            evaluator_key = _unit_of_work_key(evaluator.unit_of_work_key)
            writer_key = _unit_of_work_key(writer.unit_of_work_key)
        except Exception as exc:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring unit of work is unavailable"
            ) from exc
        if evaluator_key != writer_key:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring owners use different units of work"
            )
        self._expected_uow_key = evaluator_key

    def execute(
        self,
        command: EvaluateGovernedOptimizationMonitoringCommand,
    ) -> GovernedOptimizationMonitoringPersistedAssessment:
        """Persist a complete owner graph without lifecycle side effects."""

        _require_registration_command(command)
        self._require_unchanged_uow()
        try:
            with self._writer.atomic():
                self._require_unchanged_uow()
                evidence = self._evaluator.execute_evidence(command)
                self._require_unchanged_uow()
                _require_complete_evidence(evidence)
                persisted = self._writer.append_evidence(
                    command=command,
                    evidence=evidence,
                )
                self._require_unchanged_uow()
                return persisted
        except (
            GovernedOptimizationMonitoringPersistenceConflict,
            GovernedOptimizationMonitoringPersistenceCorruption,
            GovernedOptimizationMonitoringPersistenceUnavailable,
        ):
            raise
        except GovernedOptimizationMonitoringUnavailable as exc:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring owner graph is unavailable"
            ) from exc
        except Exception as exc:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring registration is unavailable"
            ) from exc

    def _require_unchanged_uow(self) -> None:
        try:
            evaluator_key = _unit_of_work_key(self._evaluator.unit_of_work_key)
            writer_key = _unit_of_work_key(self._writer.unit_of_work_key)
        except Exception as exc:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring unit of work is unavailable"
            ) from exc
        if evaluator_key != self._expected_uow_key or writer_key != self._expected_uow_key:
            raise GovernedOptimizationMonitoringPersistenceUnavailable(
                "R8 monitoring unit of work identity changed"
            )


class GetExactGovernedOptimizationMonitoringAssessment:
    """Read-only exact PIT facade."""

    def __init__(
        self,
        repository: GovernedOptimizationMonitoringAssessmentRepository,
    ) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactGovernedOptimizationMonitoringAssessmentCommand,
    ) -> GovernedOptimizationMonitoringPersistedAssessment | None:
        """Return one exact persisted graph or explicit absence."""

        _require_exact_command(command)
        return self._repository.get_exact(
            assessment_ref=command.assessment_ref,
            as_of=command.as_of,
        )


class AuditGovernedOptimizationMonitoringAssessments:
    """Read-only bounded internal-audit facade."""

    def __init__(
        self,
        repository: GovernedOptimizationMonitoringAssessmentRepository,
    ) -> None:
        self._repository = repository

    def execute(
        self,
        command: AuditGovernedOptimizationMonitoringAssessmentsCommand,
    ) -> GovernedOptimizationMonitoringAuditPage:
        """Return one cursor-bound immutable audit page."""

        _require_audit_command(command)
        return self._repository.list_audit(
            as_of=command.as_of,
            cursor=command.cursor,
            limit=command.limit,
        )


def _require_complete_evidence(
    evidence: GovernedOptimizationMonitoringEvaluationEvidence,
) -> None:
    if type(evidence) is not GovernedOptimizationMonitoringEvaluationEvidence:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring owner graph type is invalid"
        )
    if (
        evidence.active_result is None
        or evidence.receipt is None
        or evidence.policy is None
        or evidence.calendar is None
        or len(evidence.upstream_promotions) != 3
        or not evidence.portfolio_evidence
        or not evidence.broker_evidence
        or not evidence.observations
    ):
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "complete R8 monitoring owner graph is unavailable"
        )
    try:
        validated = evidence.assessment.validated_copy(
            policy=evidence.policy,
            calendar=evidence.calendar,
            observations=evidence.observations,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring assessment replay is unavailable"
        ) from exc
    if validated != evidence.assessment:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring assessment differs after replay"
        )


def _require_registration_command(
    command: EvaluateGovernedOptimizationMonitoringCommand,
) -> None:
    try:
        if type(command) is not EvaluateGovernedOptimizationMonitoringCommand:
            raise TypeError("registration command type differs")
        EvaluateGovernedOptimizationMonitoringCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as exc:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring registration command is malformed"
        ) from exc


def _require_exact_command(
    command: GetExactGovernedOptimizationMonitoringAssessmentCommand,
) -> None:
    try:
        if type(command) is not GetExactGovernedOptimizationMonitoringAssessmentCommand:
            raise TypeError("exact query command type differs")
        GetExactGovernedOptimizationMonitoringAssessmentCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as exc:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring exact query is malformed"
        ) from exc


def _require_audit_command(
    command: AuditGovernedOptimizationMonitoringAssessmentsCommand,
) -> None:
    try:
        if type(command) is not AuditGovernedOptimizationMonitoringAssessmentsCommand:
            raise TypeError("audit command type differs")
        AuditGovernedOptimizationMonitoringAssessmentsCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as exc:
        raise GovernedOptimizationMonitoringPersistenceUnavailable(
            "R8 monitoring audit query is malformed"
        ) from exc


def _unit_of_work_key(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError("unit_of_work_key must be an exact non-blank string")
    return value


__all__ = [
    "AuditGovernedOptimizationMonitoringAssessments",
    "AuditGovernedOptimizationMonitoringAssessmentsCommand",
    "GetExactGovernedOptimizationMonitoringAssessment",
    "GetExactGovernedOptimizationMonitoringAssessmentCommand",
    "GovernedOptimizationMonitoringAssessmentRef",
    "GovernedOptimizationMonitoringAssessmentRepository",
    "GovernedOptimizationMonitoringAssessmentWriter",
    "GovernedOptimizationMonitoringAuditEntry",
    "GovernedOptimizationMonitoringAuditPage",
    "GovernedOptimizationMonitoringPersistedAssessment",
    "GovernedOptimizationMonitoringPersistenceConflict",
    "GovernedOptimizationMonitoringPersistenceCorruption",
    "GovernedOptimizationMonitoringPersistenceUnavailable",
    "RegisterGovernedOptimizationMonitoringAssessment",
]
