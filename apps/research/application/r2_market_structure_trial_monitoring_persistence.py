"""ID-only persistence contracts for R2 trial and monitoring evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol, cast

from apps.research.application.r2_market_structure_trial_monitoring import (
    EvaluateR2MarketStructureTrialCommand,
    R2ExplanatoryTrialEvaluationEvidence,
    R2MonitoringEvaluationEvidence,
    R2TrialMonitoringUnavailable,
)


class R2TrialMonitoringPersistenceUnavailable(RuntimeError):
    """An authoritative owner, shared UoW, clock, or writer is unavailable."""


class R2TrialMonitoringPersistenceConflict(RuntimeError):
    """An immutable R2 registration identity has conflicting evidence."""


class R2TrialMonitoringPersistenceCorruption(RuntimeError):
    """Persisted R2 evidence failed strict replay."""


def derive_r2_trial_assessment_id(
    command: EvaluateR2MarketStructureTrialCommand,
) -> str:
    """Derive the immutable trial-registration identity from ID-only input."""

    _require_live_command(command)
    return (
        "r2-trial-assessment:"
        + sha256(
            (
                f"{command.policy_id}\x00{command.policy_version}\x00"
                f"{command.expected_policy_hash.lower()}\x00"
                f"{command.as_of.astimezone(UTC).isoformat()}"
            ).encode()
        ).hexdigest()
    )


def derive_r2_monitoring_assessment_id(
    command: EvaluateR2MarketStructureTrialCommand,
) -> str:
    """Derive the immutable monitoring-registration identity from ID-only input."""

    _require_live_command(command)
    return (
        "r2-monitoring-assessment:"
        + sha256(
            (
                f"{command.policy_id}\x00{command.policy_version}\x00"
                f"{command.expected_policy_hash.lower()}\x00"
                f"{command.as_of.astimezone(UTC).isoformat()}"
            ).encode()
        ).hexdigest()
    )


@dataclass(frozen=True)
class R2TrialAssessmentRef:
    """Exact persisted trial identity and evidence seal."""

    assessment_id: str
    assessment_version: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.assessment_id, "trial assessment_id")
        _require_token(self.assessment_version, "trial assessment_version")
        _require_hash(self.content_hash, "trial content_hash")


@dataclass(frozen=True)
class R2MonitoringAssessmentRef:
    """Exact persisted monitoring identity and evidence seal."""

    assessment_id: str
    assessment_version: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.assessment_id, "monitoring assessment_id")
        _require_token(self.assessment_version, "monitoring assessment_version")
        _require_hash(self.content_hash, "monitoring content_hash")


@dataclass(frozen=True)
class R2PersistedTrialAssessment:
    """Strictly restored complete trial evidence and server ledger clock."""

    reference: R2TrialAssessmentRef
    evidence: R2ExplanatoryTrialEvaluationEvidence
    ledger_recorded_at: datetime


@dataclass(frozen=True)
class R2PersistedMonitoringAssessment:
    """Strictly restored monitoring graph and its trial receipt."""

    reference: R2MonitoringAssessmentRef
    trial_reference: R2TrialAssessmentRef
    evidence: R2MonitoringEvaluationEvidence
    ledger_recorded_at: datetime


@dataclass(frozen=True)
class GetExactR2TrialAssessmentCommand:
    """Exact PIT query without latest/current semantics."""

    reference: R2TrialAssessmentRef
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.reference) is not R2TrialAssessmentRef:
            raise ValueError("trial reference is invalid")
        self.reference.__post_init__()
        _require_aware(self.as_of, "trial query as_of")


@dataclass(frozen=True)
class GetExactR2MonitoringAssessmentCommand:
    """Exact PIT query without latest/current semantics."""

    reference: R2MonitoringAssessmentRef
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.reference) is not R2MonitoringAssessmentRef:
            raise ValueError("monitoring reference is invalid")
        self.reference.__post_init__()
        _require_aware(self.as_of, "monitoring query as_of")


@dataclass(frozen=True)
class AuditR2MonitoringCommand:
    """Bounded internal audit query using an immutable snapshot cursor."""

    as_of: datetime
    cursor: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "audit as_of")
        if self.cursor is not None and (
            type(self.cursor) is not str or not self.cursor or len(self.cursor) > 4096
        ):
            raise ValueError("R2 audit cursor is invalid")
        if type(self.limit) is not int or not 1 <= self.limit <= 200:
            raise ValueError("R2 audit limit must be between 1 and 200")


@dataclass(frozen=True)
class R2MonitoringAuditEntry:
    """Safe audit projection without Promotion or retirement authority."""

    reference: R2MonitoringAssessmentRef
    trial_reference: R2TrialAssessmentRef
    policy_id: str
    policy_version: str
    assessed_at: datetime
    ledger_recorded_at: datetime
    status: str
    fact_count: int
    retirement_review_required: bool


@dataclass(frozen=True)
class R2MonitoringAuditPage:
    """One stable page from an immutable audit snapshot."""

    entries: tuple[R2MonitoringAuditEntry, ...]
    next_cursor: str | None
    as_of: datetime


class R2ExplanatoryTrialEvidenceEvaluator(Protocol):
    """Complete Phase A trial evidence boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database/snapshot identity."""

    def execute_evidence(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2ExplanatoryTrialEvaluationEvidence:
        """Reread and locally derive one complete trial graph."""


class R2MonitoringEvidenceEvaluator(Protocol):
    """Complete Phase A monitoring evidence boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database/snapshot identity."""

    def execute_evidence(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2MonitoringEvaluationEvidence:
        """Reread and locally derive one complete monitoring graph."""


class R2TrialMonitoringWriter(Protocol):
    """Private append capability retained outside public runtime graphs."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one write transaction shared with owner reads."""

    def append_trial(
        self,
        *,
        command: EvaluateR2MarketStructureTrialCommand,
        evidence: R2ExplanatoryTrialEvaluationEvidence,
    ) -> R2ExplanatoryTrialEvaluationEvidence:
        """Append or replay one complete trial assessment."""

    def append_monitoring(
        self,
        *,
        command: EvaluateR2MarketStructureTrialCommand,
        evidence: R2MonitoringEvaluationEvidence,
    ) -> R2MonitoringEvaluationEvidence:
        """Append or replay one complete monitoring assessment."""


class R2TrialMonitoringReadRepository(Protocol):
    """Read-only exact PIT and immutable-audit boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

    def get_trial_exact(
        self,
        *,
        reference: R2TrialAssessmentRef,
        as_of: datetime,
    ) -> R2PersistedTrialAssessment | None:
        """Return one exact trial receipt known at the cutoff."""

    def get_monitoring_exact(
        self,
        *,
        reference: R2MonitoringAssessmentRef,
        as_of: datetime,
    ) -> R2PersistedMonitoringAssessment | None:
        """Return one exact monitoring receipt known at the cutoff."""

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R2MonitoringAuditPage:
        """Return one immutable-snapshot audit page."""


class _R2UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction identity."""


class _R2PostInitCommand(Protocol):
    def __post_init__(self) -> None:
        """Revalidate the live command instance."""


class RegisterR2ExplanatoryTrialAssessment:
    """Persist one exact two-cycle explanatory assessment with no Promotion effect."""

    def __init__(
        self,
        *,
        evaluator: R2ExplanatoryTrialEvidenceEvaluator,
        writer: R2TrialMonitoringWriter,
    ) -> None:
        self._evaluator = evaluator
        self._writer = writer
        self._expected_uow_key = _require_shared_uow(evaluator, writer)

    def execute(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2ExplanatoryTrialEvaluationEvidence:
        """Reread, replay, and append one complete owner-derived trial graph."""

        _require_live_command(command)
        self._require_unchanged_uow()
        try:
            with self._writer.atomic():
                self._require_unchanged_uow()
                evidence = self._evaluator.execute_evidence(command).validated_copy()
                self._require_unchanged_uow()
                reread = self._evaluator.execute_evidence(command).validated_copy()
                if evidence != reread:
                    raise R2TrialMonitoringPersistenceUnavailable(
                        "R2 trial owner evidence changed during registration"
                    )
                self._require_unchanged_uow()
                persisted = self._writer.append_trial(command=command, evidence=reread)
                self._require_unchanged_uow()
                return persisted.validated_copy()
        except (
            R2TrialMonitoringPersistenceConflict,
            R2TrialMonitoringPersistenceCorruption,
            R2TrialMonitoringPersistenceUnavailable,
        ):
            raise
        except R2TrialMonitoringUnavailable as error:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 trial owner graph is unavailable"
            ) from error
        except Exception as error:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 trial registration is unavailable"
            ) from error

    def _require_unchanged_uow(self) -> None:
        if _require_shared_uow(self._evaluator, self._writer) != self._expected_uow_key:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 trial monitoring unit of work identity changed"
            )


class RegisterR2MonitoringAssessment:
    """Persist monitoring evidence without automatic retirement or Promotion."""

    def __init__(
        self,
        *,
        evaluator: R2MonitoringEvidenceEvaluator,
        writer: R2TrialMonitoringWriter,
    ) -> None:
        self._evaluator = evaluator
        self._writer = writer
        self._expected_uow_key = _require_shared_uow(evaluator, writer)

    def execute(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2MonitoringEvaluationEvidence:
        """Reread, replay, and append one assessment-scoped fact set."""

        _require_live_command(command)
        self._require_unchanged_uow()
        try:
            with self._writer.atomic():
                self._require_unchanged_uow()
                evidence = self._evaluator.execute_evidence(command).validated_copy()
                self._require_unchanged_uow()
                reread = self._evaluator.execute_evidence(command).validated_copy()
                if evidence != reread:
                    raise R2TrialMonitoringPersistenceUnavailable(
                        "R2 monitoring owner evidence changed during registration"
                    )
                self._require_unchanged_uow()
                persisted = self._writer.append_monitoring(
                    command=command,
                    evidence=reread,
                )
                self._require_unchanged_uow()
                return persisted.validated_copy()
        except (
            R2TrialMonitoringPersistenceConflict,
            R2TrialMonitoringPersistenceCorruption,
            R2TrialMonitoringPersistenceUnavailable,
        ):
            raise
        except R2TrialMonitoringUnavailable as error:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 monitoring owner graph is unavailable"
            ) from error
        except Exception as error:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 monitoring registration is unavailable"
            ) from error

    def _require_unchanged_uow(self) -> None:
        if _require_shared_uow(self._evaluator, self._writer) != self._expected_uow_key:
            raise R2TrialMonitoringPersistenceUnavailable(
                "R2 trial monitoring unit of work identity changed"
            )


class GetExactR2TrialAssessment:
    """Read one exact trial receipt at a PIT cutoff."""

    def __init__(self, repository: R2TrialMonitoringReadRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR2TrialAssessmentCommand,
    ) -> R2PersistedTrialAssessment | None:
        """Return exact evidence or explicit absence."""

        _require_live_query(command, GetExactR2TrialAssessmentCommand)
        return self._repository.get_trial_exact(
            reference=command.reference,
            as_of=command.as_of,
        )


class GetExactR2MonitoringAssessment:
    """Read one exact monitoring receipt at a PIT cutoff."""

    def __init__(self, repository: R2TrialMonitoringReadRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR2MonitoringAssessmentCommand,
    ) -> R2PersistedMonitoringAssessment | None:
        """Return exact evidence or explicit absence."""

        _require_live_query(command, GetExactR2MonitoringAssessmentCommand)
        return self._repository.get_monitoring_exact(
            reference=command.reference,
            as_of=command.as_of,
        )


class AuditR2Monitoring:
    """Read a bounded immutable internal-audit snapshot."""

    def __init__(self, repository: R2TrialMonitoringReadRepository) -> None:
        self._repository = repository

    def execute(self, command: AuditR2MonitoringCommand) -> R2MonitoringAuditPage:
        """Return one snapshot-bound audit page."""

        _require_live_query(command, AuditR2MonitoringCommand)
        return self._repository.list_audit(
            as_of=command.as_of,
            cursor=command.cursor,
            limit=command.limit,
        )


def _require_shared_uow(
    evaluator: _R2UnitOfWorkBound,
    writer: _R2UnitOfWorkBound,
) -> str:
    try:
        evaluator_key = _exact_uow_key(evaluator.unit_of_work_key)
        writer_key = _exact_uow_key(writer.unit_of_work_key)
    except Exception as error:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 trial monitoring unit of work is unavailable"
        ) from error
    if evaluator_key != writer_key:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 trial monitoring unit of work differs across owners"
        )
    return evaluator_key


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 192:
        raise TypeError("unit_of_work_key must be an exact bounded string")
    return value


def _require_live_command(command: object) -> None:
    try:
        if type(command) is not EvaluateR2MarketStructureTrialCommand:
            raise TypeError("R2 registration command type differs")
        EvaluateR2MarketStructureTrialCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 trial monitoring registration command is malformed"
        ) from error


def _require_live_query(command: object, expected_type: type[object]) -> None:
    try:
        if type(command) is not expected_type:
            raise TypeError("R2 query command type differs")
        cast(_R2PostInitCommand, command).__post_init__()
    except (AttributeError, TypeError, ValueError) as error:
        raise R2TrialMonitoringPersistenceUnavailable(
            "R2 trial monitoring query is malformed"
        ) from error


def _require_token(value: object, label: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be a bounded token")


def _require_hash(value: object, label: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{label} must be a SHA-256 digest")


def _require_aware(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


__all__ = [
    "AuditR2Monitoring",
    "AuditR2MonitoringCommand",
    "GetExactR2MonitoringAssessment",
    "GetExactR2MonitoringAssessmentCommand",
    "GetExactR2TrialAssessment",
    "GetExactR2TrialAssessmentCommand",
    "R2MonitoringAssessmentRef",
    "R2MonitoringAuditEntry",
    "R2MonitoringAuditPage",
    "R2PersistedMonitoringAssessment",
    "R2PersistedTrialAssessment",
    "R2TrialAssessmentRef",
    "R2ExplanatoryTrialEvidenceEvaluator",
    "R2MonitoringEvidenceEvaluator",
    "R2TrialMonitoringPersistenceConflict",
    "R2TrialMonitoringPersistenceCorruption",
    "R2TrialMonitoringPersistenceUnavailable",
    "R2TrialMonitoringWriter",
    "RegisterR2ExplanatoryTrialAssessment",
    "RegisterR2MonitoringAssessment",
    "derive_r2_monitoring_assessment_id",
    "derive_r2_trial_assessment_id",
]
