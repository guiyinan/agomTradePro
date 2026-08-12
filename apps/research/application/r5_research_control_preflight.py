"""Read-only R5 research-control preflight over canonical owner projections."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from apps.fixed_income.domain.evidence import canonical_hash
from apps.research.domain.r5_relative_value_monitoring import (
    R5MonitoringAssessmentStatus,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringFixedIncomeEvidence,
    _require_aware,
    _require_hash,
    _require_token,
)


class R5ResearchControlUnavailable(RuntimeError):
    """The caller command or shared read boundary is invalid."""


class R5ResearchControlPreflightStatus(StrEnum):
    """The only two states exposed by the research-control boundary."""

    ELIGIBLE_FOR_MANUAL_CONSUMER_REVIEW = "eligible_for_manual_consumer_review"
    BLOCKED = "blocked"


class R5ResearchControlBlockerCode(StrEnum):
    """Stable fail-closed reasons; none grants publication or decision authority."""

    ACTIVE_LIFECYCLE_UNAVAILABLE = "active_lifecycle_unavailable"
    MONITORING_ASSESSMENT_UNAVAILABLE = "monitoring_assessment_unavailable"
    FIXED_INCOME_OWNER_SEAL_UNAVAILABLE = "fixed_income_owner_seal_unavailable"
    LATEST_MONITORING_BREACHED = "latest_monitoring_breached"
    LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW = "latest_monitoring_requires_retirement_review"
    OWNER_GRAPH_SUBSTITUTED = "owner_graph_substituted"
    OWNER_GRAPH_CHANGED_DURING_PREFLIGHT = "owner_graph_changed_during_preflight"
    OWNER_PROVIDER_UNAVAILABLE = "owner_provider_unavailable"
    UNIT_OF_WORK_CHANGED = "unit_of_work_changed"


@dataclass(frozen=True)
class EvaluateR5ResearchControlPreflightCommand:
    """ID-only PIT request with no assessment or health-result selector."""

    scope_id: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R5 research-control scope_id", maximum=300)
        _require_aware(self.as_of, "R5 research-control as_of")


@dataclass(frozen=True)
class R5ResearchControlMonitoringEvidence:
    """Strict projection of the server-selected latest complete assessment."""

    assessment_id: str
    assessment_hash: str
    active_lifecycle: R5MonitoringActiveLifecycle
    fixed_income: R5MonitoringFixedIncomeEvidence
    latest_period_id: str
    latest_period_end: datetime
    evaluated_at: datetime
    ledger_recorded_at: datetime
    status: R5MonitoringAssessmentStatus
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        assessment_id: str,
        assessment_hash: str,
        active_lifecycle: R5MonitoringActiveLifecycle,
        fixed_income: R5MonitoringFixedIncomeEvidence,
        latest_period_id: str,
        latest_period_end: datetime,
        evaluated_at: datetime,
        ledger_recorded_at: datetime,
        status: R5MonitoringAssessmentStatus,
    ) -> R5ResearchControlMonitoringEvidence:
        """Create a safety-fixed projection from one fully restored ledger row."""

        return cls(
            assessment_id=assessment_id,
            assessment_hash=assessment_hash,
            active_lifecycle=active_lifecycle,
            fixed_income=fixed_income,
            latest_period_id=latest_period_id,
            latest_period_end=latest_period_end,
            evaluated_at=evaluated_at,
            ledger_recorded_at=ledger_recorded_at,
            status=status,
        )

    def __post_init__(self) -> None:
        _require_token(self.assessment_id, "R5 research-control assessment_id")
        _require_hash(self.assessment_hash, "R5 research-control assessment_hash")
        if type(self.active_lifecycle) is not R5MonitoringActiveLifecycle:
            raise TypeError("R5 research-control active lifecycle type differs")
        if type(self.fixed_income) is not R5MonitoringFixedIncomeEvidence:
            raise TypeError("R5 research-control fixed-income evidence type differs")
        R5MonitoringActiveLifecycle.__post_init__(self.active_lifecycle)
        R5MonitoringFixedIncomeEvidence.__post_init__(self.fixed_income)
        _require_hash(self.latest_period_id, "R5 research-control latest_period_id")
        for label, value in (
            ("latest_period_end", self.latest_period_end),
            ("evaluated_at", self.evaluated_at),
            ("ledger_recorded_at", self.ledger_recorded_at),
        ):
            _require_aware(value, f"R5 research-control {label}")
        if not (
            self.fixed_income.recorded_at
            <= self.latest_period_end
            <= self.evaluated_at
            <= self.ledger_recorded_at
        ):
            raise ValueError("R5 research-control monitoring clocks differ")
        if self.status not in {
            R5MonitoringAssessmentStatus.HEALTHY,
            R5MonitoringAssessmentStatus.BREACHED,
            R5MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED,
        }:
            raise ValueError("R5 research-control requires a complete assessment")
        if (
            self.fixed_income.owner_seal_hash
            not in self.active_lifecycle.fixed_income_owner_seal_hashes
        ):
            raise ValueError("R5 research-control fixed-income seal is outside the active trial")
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R5 research-control monitoring evidence must remain research-only")
        object.__setattr__(self, "content_hash", _monitoring_evidence_hash(self))

    def validated_copy(self) -> R5ResearchControlMonitoringEvidence:
        """Deeply reconstruct this exact owner projection."""

        copied = R5ResearchControlMonitoringEvidence.create(
            assessment_id=self.assessment_id,
            assessment_hash=self.assessment_hash,
            active_lifecycle=self.active_lifecycle.validated_copy(),
            fixed_income=self.fixed_income.validated_copy(),
            latest_period_id=self.latest_period_id,
            latest_period_end=self.latest_period_end,
            evaluated_at=self.evaluated_at,
            ledger_recorded_at=self.ledger_recorded_at,
            status=self.status,
        )
        if copied != self:
            raise ValueError("R5 research-control monitoring evidence differs after replay")
        return copied


def _monitoring_evidence_hash(value: R5ResearchControlMonitoringEvidence) -> str:
    return canonical_hash(
        {
            "schema": "research-r5-control-monitoring-evidence.v1",
            "assessment": (value.assessment_id, value.assessment_hash),
            "active_lifecycle_hash": value.active_lifecycle.content_hash,
            "fixed_income_hash": value.fixed_income.content_hash,
            "latest_period": (value.latest_period_id, value.latest_period_end),
            "clocks": (value.evaluated_at, value.ledger_recorded_at),
            "status": value.status,
            "research_only": True,
            "must_not_publish_current": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
    )


@dataclass(frozen=True)
class R5ResearchControlPreflightResult:
    """Read-only gate result that never grants current, decision, or execution use."""

    scope_id: str
    as_of: datetime
    status: R5ResearchControlPreflightStatus
    blocker_codes: tuple[R5ResearchControlBlockerCode, ...]
    active_lifecycle_hash: str | None
    monitoring_assessment_hash: str | None
    fixed_income_owner_seal_hash: str | None
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R5 research-control result scope_id", maximum=300)
        _require_aware(self.as_of, "R5 research-control result as_of")
        if type(self.status) is not R5ResearchControlPreflightStatus:
            raise TypeError("R5 research-control result status differs")
        if type(self.blocker_codes) is not tuple or self.blocker_codes != tuple(
            sorted(set(self.blocker_codes), key=lambda item: item.value)
        ):
            raise ValueError("R5 research-control blockers are not canonical")
        for item in self.blocker_codes:
            if type(item) is not R5ResearchControlBlockerCode:
                raise TypeError("R5 research-control blocker type differs")
        if (self.status is R5ResearchControlPreflightStatus.BLOCKED) != bool(self.blocker_codes):
            raise ValueError("R5 research-control status and blockers differ")
        for label, value in (
            ("active_lifecycle_hash", self.active_lifecycle_hash),
            ("monitoring_assessment_hash", self.monitoring_assessment_hash),
            ("fixed_income_owner_seal_hash", self.fixed_income_owner_seal_hash),
        ):
            if value is not None:
                _require_hash(value, f"R5 research-control result {label}")
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R5 research-control result safety boundary differs")
        object.__setattr__(self, "content_hash", canonical_hash(self._hash_payload()))

    def _hash_payload(self) -> dict[str, object]:
        return {
            "schema": "research-r5-control-preflight-result.v1",
            "scope_id": self.scope_id,
            "as_of": self.as_of,
            "status": self.status,
            "blockers": self.blocker_codes,
            "active_lifecycle_hash": self.active_lifecycle_hash,
            "monitoring_assessment_hash": self.monitoring_assessment_hash,
            "fixed_income_owner_seal_hash": self.fixed_income_owner_seal_hash,
            "research_only": True,
            "must_not_publish_current": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }


class R5ResearchControlActiveLifecycleProvider(Protocol):
    """Canonical Research active-lifecycle exact reader."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

    def get_active(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R5MonitoringActiveLifecycle | None:
        """Return the server-selected active lifecycle or explicit absence."""


class R5ResearchControlMonitoringProvider(Protocol):
    """Server-selecting latest-complete monitoring assessment reader."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

    def get_latest_complete(
        self,
        *,
        active_lifecycle: R5MonitoringActiveLifecycle,
        as_of: datetime,
    ) -> R5ResearchControlMonitoringEvidence | None:
        """Select by active decision and latest complete period, never caller health."""


class R5ResearchControlFixedIncomeProvider(Protocol):
    """Canonical FixedIncome result and owner-seal exact reader."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

    def get_exact(
        self,
        *,
        evidence: R5MonitoringFixedIncomeEvidence,
        as_of: datetime,
    ) -> R5MonitoringFixedIncomeEvidence | None:
        """Reread one exact FixedIncome owner projection."""


class R5ResearchControlUnitOfWork(Protocol):
    """Shared read transaction and trusted server clock."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared read transaction."""

    def server_now(self) -> datetime:
        """Read the trusted server clock inside the transaction."""


@dataclass(frozen=True)
class _OwnerGraph:
    active_lifecycle: R5MonitoringActiveLifecycle | None
    monitoring: R5ResearchControlMonitoringEvidence | None
    fixed_income: R5MonitoringFixedIncomeEvidence | None


class EvaluateR5ResearchControlPreflight:
    """Double-read exact owners and emit only a non-authoritative review gate."""

    def __init__(
        self,
        *,
        active_lifecycle_provider: R5ResearchControlActiveLifecycleProvider,
        monitoring_provider: R5ResearchControlMonitoringProvider,
        fixed_income_provider: R5ResearchControlFixedIncomeProvider,
        unit_of_work: R5ResearchControlUnitOfWork,
    ) -> None:
        self._active_lifecycle_provider = active_lifecycle_provider
        self._monitoring_provider = monitoring_provider
        self._fixed_income_provider = fixed_income_provider
        self._unit_of_work = unit_of_work
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise R5ResearchControlUnavailable(
                "R5 research-control unit of work is unavailable"
            ) from error
        if len(set(keys)) != 1:
            raise R5ResearchControlUnavailable(
                "R5 research-control owners use different unit of work identities"
            )
        self._expected_uow_key = keys[0]

    def execute(
        self,
        command: EvaluateR5ResearchControlPreflightCommand,
    ) -> R5ResearchControlPreflightResult:
        """Evaluate the exact latest graph without any write or consumer side effect."""

        self._require_command(command)
        try:
            with self._unit_of_work.atomic():
                self._require_unchanged_uow()
                server_now = self._unit_of_work.server_now()
                _require_aware(server_now, "R5 research-control server_now")
                if command.as_of > server_now:
                    raise R5ResearchControlUnavailable(
                        "R5 research-control command uses a future as_of"
                    )
                first = self._read_graph(command)
                self._require_unchanged_uow()
                second = self._read_graph(command)
                self._require_unchanged_uow()
        except R5ResearchControlUnavailable:
            raise
        except _UnitOfWorkChanged:
            return self._blocked(
                command,
                R5ResearchControlBlockerCode.UNIT_OF_WORK_CHANGED,
            )
        except Exception:
            return self._blocked(
                command,
                R5ResearchControlBlockerCode.OWNER_PROVIDER_UNAVAILABLE,
            )
        if first != second:
            return self._blocked(
                command,
                R5ResearchControlBlockerCode.OWNER_GRAPH_CHANGED_DURING_PREFLIGHT,
            )
        return self._evaluate_graph(command, second)

    def _read_graph(
        self,
        command: EvaluateR5ResearchControlPreflightCommand,
    ) -> _OwnerGraph:
        self._require_unchanged_uow()
        active = _copy_active(
            self._active_lifecycle_provider.get_active(
                scope_id=command.scope_id,
                as_of=command.as_of,
            )
        )
        self._require_unchanged_uow()
        if active is None:
            return _OwnerGraph(None, None, None)
        monitoring = _copy_monitoring(
            self._monitoring_provider.get_latest_complete(
                active_lifecycle=active,
                as_of=command.as_of,
            )
        )
        self._require_unchanged_uow()
        if monitoring is None:
            return _OwnerGraph(active, None, None)
        fixed_income = _copy_fixed_income(
            self._fixed_income_provider.get_exact(
                evidence=monitoring.fixed_income,
                as_of=command.as_of,
            )
        )
        self._require_unchanged_uow()
        return _OwnerGraph(active, monitoring, fixed_income)

    def _evaluate_graph(
        self,
        command: EvaluateR5ResearchControlPreflightCommand,
        graph: _OwnerGraph,
    ) -> R5ResearchControlPreflightResult:
        active = graph.active_lifecycle
        monitoring = graph.monitoring
        fixed_income = graph.fixed_income
        if active is None:
            return self._blocked(
                command,
                R5ResearchControlBlockerCode.ACTIVE_LIFECYCLE_UNAVAILABLE,
            )
        if monitoring is None:
            return self._blocked(
                command,
                R5ResearchControlBlockerCode.MONITORING_ASSESSMENT_UNAVAILABLE,
                active=active,
            )
        if fixed_income is None:
            return self._blocked(
                command,
                R5ResearchControlBlockerCode.FIXED_INCOME_OWNER_SEAL_UNAVAILABLE,
                active=active,
                monitoring=monitoring,
            )
        if not (
            active == monitoring.active_lifecycle
            and fixed_income == monitoring.fixed_income
            and active.scope_id == command.scope_id
            and active.recorded_at <= command.as_of < active.valid_until
            and monitoring.ledger_recorded_at <= command.as_of
            and monitoring.evaluated_at <= command.as_of
            and fixed_income.recorded_at <= command.as_of
        ):
            return self._blocked(
                command,
                R5ResearchControlBlockerCode.OWNER_GRAPH_SUBSTITUTED,
                active=active,
                monitoring=monitoring,
                fixed_income=fixed_income,
            )
        if monitoring.status is R5MonitoringAssessmentStatus.BREACHED:
            return self._blocked(
                command,
                R5ResearchControlBlockerCode.LATEST_MONITORING_BREACHED,
                active=active,
                monitoring=monitoring,
                fixed_income=fixed_income,
            )
        if monitoring.status is R5MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED:
            return self._blocked(
                command,
                R5ResearchControlBlockerCode.LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW,
                active=active,
                monitoring=monitoring,
                fixed_income=fixed_income,
            )
        return R5ResearchControlPreflightResult(
            scope_id=command.scope_id,
            as_of=command.as_of,
            status=(R5ResearchControlPreflightStatus.ELIGIBLE_FOR_MANUAL_CONSUMER_REVIEW),
            blocker_codes=(),
            active_lifecycle_hash=active.content_hash,
            monitoring_assessment_hash=monitoring.assessment_hash,
            fixed_income_owner_seal_hash=fixed_income.owner_seal_hash,
        )

    @staticmethod
    def _blocked(
        command: EvaluateR5ResearchControlPreflightCommand,
        blocker: R5ResearchControlBlockerCode,
        *,
        active: R5MonitoringActiveLifecycle | None = None,
        monitoring: R5ResearchControlMonitoringEvidence | None = None,
        fixed_income: R5MonitoringFixedIncomeEvidence | None = None,
    ) -> R5ResearchControlPreflightResult:
        return R5ResearchControlPreflightResult(
            scope_id=command.scope_id,
            as_of=command.as_of,
            status=R5ResearchControlPreflightStatus.BLOCKED,
            blocker_codes=(blocker,),
            active_lifecycle_hash=None if active is None else active.content_hash,
            monitoring_assessment_hash=(None if monitoring is None else monitoring.assessment_hash),
            fixed_income_owner_seal_hash=(
                None if fixed_income is None else fixed_income.owner_seal_hash
            ),
        )

    @staticmethod
    def _require_command(command: object) -> None:
        try:
            if type(command) is not EvaluateR5ResearchControlPreflightCommand:
                raise TypeError
            EvaluateR5ResearchControlPreflightCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R5ResearchControlUnavailable(
                "R5 research-control command is malformed"
            ) from error

    def _current_uow_keys(self) -> tuple[str, ...]:
        values: tuple[object, ...] = (
            self._active_lifecycle_provider.unit_of_work_key,
            self._monitoring_provider.unit_of_work_key,
            self._fixed_income_provider.unit_of_work_key,
            self._unit_of_work.unit_of_work_key,
        )
        return tuple(_exact_uow_key(value) for value in values)

    def _require_unchanged_uow(self) -> None:
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise _UnitOfWorkChanged from error
        if any(value != self._expected_uow_key for value in keys):
            raise _UnitOfWorkChanged


class _UnitOfWorkChanged(RuntimeError):
    pass


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError("R5 research-control unit_of_work_key must be an exact string")
    return value


def _copy_active(value: object) -> R5MonitoringActiveLifecycle | None:
    if value is None:
        return None
    if type(value) is not R5MonitoringActiveLifecycle:
        raise TypeError("R5 research-control active provider returned another type")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("R5 research-control active lifecycle was substituted")
    return copied


def _copy_monitoring(value: object) -> R5ResearchControlMonitoringEvidence | None:
    if value is None:
        return None
    if type(value) is not R5ResearchControlMonitoringEvidence:
        raise TypeError("R5 research-control monitoring provider returned another type")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("R5 research-control monitoring evidence was substituted")
    return copied


def _copy_fixed_income(value: object) -> R5MonitoringFixedIncomeEvidence | None:
    if value is None:
        return None
    if type(value) is not R5MonitoringFixedIncomeEvidence:
        raise TypeError("R5 research-control FixedIncome provider returned another type")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("R5 research-control FixedIncome evidence was substituted")
    return copied


__all__ = [
    "EvaluateR5ResearchControlPreflight",
    "EvaluateR5ResearchControlPreflightCommand",
    "R5ResearchControlActiveLifecycleProvider",
    "R5ResearchControlBlockerCode",
    "R5ResearchControlFixedIncomeProvider",
    "R5ResearchControlMonitoringEvidence",
    "R5ResearchControlMonitoringProvider",
    "R5ResearchControlPreflightResult",
    "R5ResearchControlPreflightStatus",
    "R5ResearchControlUnitOfWork",
    "R5ResearchControlUnavailable",
]
