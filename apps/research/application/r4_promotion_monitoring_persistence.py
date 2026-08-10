"""ID-only persistence and exact PIT contracts for R4 monitoring."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringEvaluationEvidence,
    R4MonitoringUnavailable,
)
from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_evidence import (
    R4PromotionR3AttestationEvidence,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringAssessment,
    R4MonitoringAssessmentStatus,
    R4MonitoringObservation,
    R4MonitoringPeriodCalendar,
    R4MonitoringPolicy,
)
from apps.research.domain.r4_promotion_record_seal import (
    R4PromotionPortfolioRecordSeal,
)


class R4MonitoringPersistenceConflict(RuntimeError):
    """An immutable command or raw-fact identity has another winner."""


class R4MonitoringPersistenceCorruption(RuntimeError):
    """Persisted R4 monitoring evidence failed strict replay."""


class R4MonitoringPersistenceUnavailable(RuntimeError):
    """A trusted owner, clock, cutoff, or write capability is unavailable."""


def r4_monitoring_assessment_id(
    *,
    active_decision: R4PromotionDecisionIdentity,
    expected_policy_hash: str,
    evaluated_at: datetime,
) -> str:
    """Derive the immutable ID-only registration identity."""

    _require_hash(expected_policy_hash, "expected_policy_hash")
    _require_aware(evaluated_at, "evaluated_at")
    digest = sha256(
        (
            f"{active_decision.decision_id}\x00"
            f"{active_decision.decision_version}\x00"
            f"{active_decision.content_hash.lower()}\x00"
            f"{expected_policy_hash.lower()}\x00"
            f"{evaluated_at.astimezone(UTC).isoformat()}"
        ).encode()
    ).hexdigest()
    return f"r4-monitoring-assessment:{digest}"


@dataclass(frozen=True)
class R4MonitoringAssessmentRef:
    """Exact persisted assessment identity and canonical content seal."""

    assessment_id: str
    assessment_hash: str

    def __post_init__(self) -> None:
        _require_token(self.assessment_id, "assessment_id")
        _require_hash(self.assessment_hash, "assessment_hash")


@dataclass(frozen=True)
class GetExactR4MonitoringAssessmentCommand:
    """Exact PIT query accepting no current/latest semantics."""

    assessment_ref: R4MonitoringAssessmentRef
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.assessment_ref) is not R4MonitoringAssessmentRef:
            raise ValueError("assessment_ref is invalid")
        self.assessment_ref.__post_init__()
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class AuditR4MonitoringAssessmentsCommand:
    """Bounded internal audit request with a cursor-bound PIT cutoff."""

    as_of: datetime
    cursor: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        if self.cursor is not None and (
            not isinstance(self.cursor, str) or not self.cursor or len(self.cursor) > 4096
        ):
            raise ValueError("R4 monitoring audit cursor is invalid")
        if type(self.limit) is not int or self.limit < 1 or self.limit > 200:
            raise ValueError("R4 monitoring audit limit must be between 1 and 200")


@dataclass(frozen=True)
class R4MonitoringPersistedAssessment:
    """Strictly restored complete owner graph and local assessment."""

    assessment_ref: R4MonitoringAssessmentRef
    active_decision: R4PromotionDecision
    portfolio_result: R4PromotionPortfolioRecordSeal
    current_r3_attestation: R4PromotionR3AttestationEvidence
    policy: R4MonitoringPolicy
    period_calendar: R4MonitoringPeriodCalendar
    observations: tuple[R4MonitoringObservation, ...]
    assessment: R4MonitoringAssessment
    ledger_recorded_at: datetime


@dataclass(frozen=True)
class R4MonitoringAuditEntry:
    """Safe internal audit projection without lifecycle authority."""

    assessment_ref: R4MonitoringAssessmentRef
    active_decision: R4PromotionDecisionIdentity
    policy_id: str
    policy_version: str
    evaluated_at: datetime
    ledger_recorded_at: datetime
    status: R4MonitoringAssessmentStatus
    observation_count: int
    blockers: tuple[str, ...]
    review_reason_codes: tuple[str, ...]
    retirement_review_required: bool


@dataclass(frozen=True)
class R4MonitoringAuditPage:
    """One immutable-snapshot page of internal assessment entries."""

    entries: tuple[R4MonitoringAuditEntry, ...]
    next_cursor: str | None
    as_of: datetime


class R4MonitoringEvidenceEvaluator(Protocol):
    """Phase A exact owner reread boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner transaction identity."""

    def execute_evidence(
        self,
        command: EvaluateR4PromotionMonitoringCommand,
    ) -> R4MonitoringEvaluationEvidence:
        """Re-read all six owners and locally recompute one assessment."""


class R4MonitoringAssessmentWriter(Protocol):
    """Private append capability retained outside public runtime graphs."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the exact write transaction shared by owner reads."""

    def append_evidence(
        self,
        *,
        command: EvaluateR4PromotionMonitoringCommand,
        evidence: R4MonitoringEvaluationEvidence,
    ) -> R4MonitoringPersistedAssessment:
        """Append one strict replay of the complete owner graph."""


class R4MonitoringAssessmentRepository(Protocol):
    """Public read-only exact PIT and internal-audit boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

    def get_exact(
        self,
        *,
        assessment_ref: R4MonitoringAssessmentRef,
        as_of: datetime,
    ) -> R4MonitoringPersistedAssessment | None:
        """Return one exact graph knowable at the cutoff or absence."""

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R4MonitoringAuditPage:
        """Return one immutable-snapshot audit page."""


class RegisterR4MonitoringAssessment:
    """Re-read Phase A owners and append only within their shared DB UoW."""

    def __init__(
        self,
        *,
        evaluator: R4MonitoringEvidenceEvaluator,
        writer: R4MonitoringAssessmentWriter,
    ) -> None:
        self._evaluator = evaluator
        self._writer = writer
        try:
            evaluator_key = _exact_unit_of_work_key(evaluator.unit_of_work_key)
            writer_key = _exact_unit_of_work_key(writer.unit_of_work_key)
        except Exception as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring unit of work is unavailable"
            ) from error
        if evaluator_key != writer_key:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring owners use different units of work"
            )
        self._expected_uow_key = evaluator_key

    def execute(
        self,
        command: EvaluateR4PromotionMonitoringCommand,
    ) -> R4MonitoringPersistedAssessment:
        """Persist one complete exact-reread graph with no lifecycle side effect."""

        _require_live_registration_command(command)
        self._require_unchanged_uow()
        try:
            with self._writer.atomic():
                self._require_unchanged_uow()
                evidence = self._evaluator.execute_evidence(command)
                self._require_unchanged_uow()
                _require_complete_owner_graph(evidence)
                persisted = self._writer.append_evidence(
                    command=command,
                    evidence=evidence,
                )
                self._require_unchanged_uow()
                return persisted
        except (
            R4MonitoringPersistenceConflict,
            R4MonitoringPersistenceCorruption,
            R4MonitoringPersistenceUnavailable,
        ):
            raise
        except R4MonitoringUnavailable as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring owner graph is unavailable"
            ) from error
        except Exception as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring registration is unavailable"
            ) from error

    def _require_unchanged_uow(self) -> None:
        try:
            evaluator_key = _exact_unit_of_work_key(self._evaluator.unit_of_work_key)
            writer_key = _exact_unit_of_work_key(self._writer.unit_of_work_key)
        except Exception as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring unit of work is unavailable"
            ) from error
        if evaluator_key != self._expected_uow_key or writer_key != self._expected_uow_key:
            raise R4MonitoringPersistenceUnavailable("R4 monitoring unit of work identity changed")


class GetExactR4MonitoringAssessment:
    """Read-only exact PIT façade."""

    def __init__(self, repository: R4MonitoringAssessmentRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR4MonitoringAssessmentCommand,
    ) -> R4MonitoringPersistedAssessment | None:
        """Return one exact persisted graph or explicit absence."""

        _require_live_exact_command(command)
        return self._repository.get_exact(
            assessment_ref=command.assessment_ref,
            as_of=command.as_of,
        )


class AuditR4MonitoringAssessments:
    """Read-only bounded internal-audit façade."""

    def __init__(self, repository: R4MonitoringAssessmentRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: AuditR4MonitoringAssessmentsCommand,
    ) -> R4MonitoringAuditPage:
        """Return one cursor-bound immutable audit page."""

        _require_live_audit_command(command)
        return self._repository.list_audit(
            as_of=command.as_of,
            cursor=command.cursor,
            limit=command.limit,
        )


def _require_complete_owner_graph(evidence: R4MonitoringEvaluationEvidence) -> None:
    if type(evidence) is not R4MonitoringEvaluationEvidence:
        raise R4MonitoringPersistenceUnavailable("R4 monitoring owner graph type is invalid")
    if (
        evidence.active_decision is None
        or evidence.portfolio_result is None
        or evidence.current_r3_attestation is None
        or evidence.policy is None
        or evidence.period_calendar is None
        or not evidence.observations
    ):
        raise R4MonitoringPersistenceUnavailable(
            "complete R4 monitoring owner graph is unavailable"
        )


def _require_live_registration_command(
    command: EvaluateR4PromotionMonitoringCommand,
) -> None:
    try:
        if type(command) is not EvaluateR4PromotionMonitoringCommand:
            raise TypeError("registration command type differs")
        EvaluateR4PromotionMonitoringCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise R4MonitoringPersistenceUnavailable(
            "R4 monitoring registration command is malformed"
        ) from error


def _require_live_exact_command(command: GetExactR4MonitoringAssessmentCommand) -> None:
    try:
        if type(command) is not GetExactR4MonitoringAssessmentCommand:
            raise TypeError("exact query command type differs")
        GetExactR4MonitoringAssessmentCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise R4MonitoringPersistenceUnavailable(
            "R4 monitoring exact query is malformed"
        ) from error


def _require_live_audit_command(command: AuditR4MonitoringAssessmentsCommand) -> None:
    try:
        if type(command) is not AuditR4MonitoringAssessmentsCommand:
            raise TypeError("audit command type differs")
        AuditR4MonitoringAssessmentsCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise R4MonitoringPersistenceUnavailable(
            "R4 monitoring audit query is malformed"
        ) from error


def _require_token(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be a bounded non-blank token")


def _exact_unit_of_work_key(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError("unit_of_work_key must be an exact non-blank string")
    return value


def _require_hash(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{label} must be a SHA-256 digest")


def _require_aware(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


__all__ = [
    "AuditR4MonitoringAssessments",
    "AuditR4MonitoringAssessmentsCommand",
    "GetExactR4MonitoringAssessment",
    "GetExactR4MonitoringAssessmentCommand",
    "R4MonitoringAssessmentRef",
    "R4MonitoringAssessmentRepository",
    "R4MonitoringAssessmentWriter",
    "R4MonitoringAuditEntry",
    "R4MonitoringAuditPage",
    "R4MonitoringPersistedAssessment",
    "R4MonitoringPersistenceConflict",
    "R4MonitoringPersistenceCorruption",
    "R4MonitoringPersistenceUnavailable",
    "RegisterR4MonitoringAssessment",
    "r4_monitoring_assessment_id",
]
