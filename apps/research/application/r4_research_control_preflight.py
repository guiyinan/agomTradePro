"""Read-only R4 research-control preflight over canonical owner evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringEvaluationEvidence,
)
from apps.research.application.r4_promotion_monitoring_persistence import (
    R4MonitoringAssessmentRef,
    r4_monitoring_assessment_id,
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
    evaluate_r4_promotion_monitoring,
)
from apps.research.domain.r4_promotion_record_seal import (
    R4PromotionPortfolioRecordSeal,
)
from apps.research.domain.r4_promotion_scope_policy import _hash_payload


class R4ResearchControlUnavailable(RuntimeError):
    """The caller command or shared canonical read boundary is invalid."""


class R4ResearchControlPreflightStatus(StrEnum):
    """The only states exposed by the R4 research-control boundary."""

    ELIGIBLE_FOR_MANUAL_CONSUMER_REVIEW = "eligible_for_manual_consumer_review"
    BLOCKED = "blocked"


class R4ResearchControlBlockerCode(StrEnum):
    """Stable fail-closed reasons without publication or decision authority."""

    ACTIVE_PROMOTION_UNAVAILABLE = "active_promotion_unavailable"
    MONITORING_ASSESSMENT_UNAVAILABLE = "monitoring_assessment_unavailable"
    OWNER_GRAPH_UNAVAILABLE = "owner_graph_unavailable"
    LATEST_MONITORING_BREACHED = "latest_monitoring_breached"
    LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW = "latest_monitoring_requires_retirement_review"
    OWNER_GRAPH_NOT_HEALTHY = "owner_graph_not_healthy"
    OWNER_GRAPH_SUBSTITUTED = "owner_graph_substituted"
    OWNER_GRAPH_CHANGED_DURING_PREFLIGHT = "owner_graph_changed_during_preflight"
    OWNER_PROVIDER_UNAVAILABLE = "owner_provider_unavailable"
    UNIT_OF_WORK_CHANGED = "unit_of_work_changed"


@dataclass(frozen=True)
class EvaluateR4ResearchControlPreflightCommand:
    """Scope/cutoff-only request with no assessment or health selector."""

    scope_id: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R4 research-control scope_id", maximum=300)
        _require_aware(self.as_of, "R4 research-control as_of")


@dataclass(frozen=True)
class R4ResearchControlMonitoringEvidence:
    """Strict projection of one server-selected latest complete assessment."""

    assessment_ref: R4MonitoringAssessmentRef
    active_decision: R4PromotionDecision
    portfolio_result: R4PromotionPortfolioRecordSeal
    current_r3_attestation: R4PromotionR3AttestationEvidence
    policy: R4MonitoringPolicy
    period_calendar: R4MonitoringPeriodCalendar
    observations: tuple[R4MonitoringObservation, ...]
    assessment: R4MonitoringAssessment
    latest_period_id: str
    latest_period_end: datetime
    ledger_recorded_at: datetime
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        active_decision: R4PromotionDecision,
        portfolio_result: R4PromotionPortfolioRecordSeal,
        current_r3_attestation: R4PromotionR3AttestationEvidence,
        policy: R4MonitoringPolicy,
        period_calendar: R4MonitoringPeriodCalendar,
        observations: tuple[R4MonitoringObservation, ...],
        assessment: R4MonitoringAssessment,
        ledger_recorded_at: datetime,
    ) -> R4ResearchControlMonitoringEvidence:
        """Create the projection from one fully restored monitoring ledger row."""

        completed = tuple(
            entry
            for entry in period_calendar.entries
            if entry.period_end <= assessment.evaluated_at
        )
        if not completed:
            raise ValueError("R4 research-control monitoring has no complete period")
        identity = R4PromotionDecisionIdentity.from_decision(active_decision)
        return cls(
            assessment_ref=R4MonitoringAssessmentRef(
                assessment_id=r4_monitoring_assessment_id(
                    active_decision=identity,
                    expected_policy_hash=policy.content_hash,
                    evaluated_at=assessment.evaluated_at,
                ),
                assessment_hash=assessment.content_hash,
            ),
            active_decision=active_decision,
            portfolio_result=portfolio_result,
            current_r3_attestation=current_r3_attestation,
            policy=policy,
            period_calendar=period_calendar,
            observations=observations,
            assessment=assessment,
            latest_period_id=completed[-1].period_id,
            latest_period_end=completed[-1].period_end,
            ledger_recorded_at=ledger_recorded_at,
        )

    def __post_init__(self) -> None:
        _require_monitoring_evidence_types(self)
        replayed = _replay_assessment(
            active_decision=self.active_decision,
            portfolio_result=self.portfolio_result,
            current_r3_attestation=self.current_r3_attestation,
            policy=self.policy,
            period_calendar=self.period_calendar,
            observations=self.observations,
            assessment=self.assessment,
        )
        if replayed != self.assessment:
            raise ValueError("R4 research-control monitoring assessment differs after replay")
        identity = R4PromotionDecisionIdentity.from_decision(self.active_decision)
        expected_ref = R4MonitoringAssessmentRef(
            assessment_id=r4_monitoring_assessment_id(
                active_decision=identity,
                expected_policy_hash=self.policy.content_hash,
                evaluated_at=self.assessment.evaluated_at,
            ),
            assessment_hash=self.assessment.content_hash,
        )
        if self.assessment_ref != expected_ref:
            raise ValueError("R4 research-control assessment identity differs")
        completed = tuple(
            entry
            for entry in self.period_calendar.entries
            if entry.period_end <= self.assessment.evaluated_at
        )
        if not completed or (
            self.latest_period_id,
            self.latest_period_end,
        ) != (completed[-1].period_id, completed[-1].period_end):
            raise ValueError("R4 research-control latest complete period differs")
        expected_period_ids = tuple(item.period_id for item in completed)
        if tuple(item.period_id for item in self.observations) != expected_period_ids:
            raise ValueError("R4 research-control monitoring period coverage is incomplete")
        _require_aware(self.ledger_recorded_at, "R4 research-control ledger_recorded_at")
        if not self.latest_period_end <= self.assessment.evaluated_at <= self.ledger_recorded_at:
            raise ValueError("R4 research-control monitoring clocks differ")
        if self.assessment.status not in {
            R4MonitoringAssessmentStatus.HEALTHY,
            R4MonitoringAssessmentStatus.BREACHED,
            R4MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED,
        }:
            raise ValueError("R4 research-control requires a complete assessment")
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R4 research-control monitoring evidence must remain research-only")
        object.__setattr__(self, "content_hash", _monitoring_evidence_hash(self))

    def validated_copy(self) -> R4ResearchControlMonitoringEvidence:
        """Deeply replay this exact monitoring owner projection."""

        copied = R4ResearchControlMonitoringEvidence.create(
            active_decision=self.active_decision,
            portfolio_result=self.portfolio_result,
            current_r3_attestation=self.current_r3_attestation,
            policy=self.policy,
            period_calendar=self.period_calendar,
            observations=self.observations,
            assessment=self.assessment,
            ledger_recorded_at=self.ledger_recorded_at,
        )
        if copied != self:
            raise ValueError("R4 research-control monitoring evidence differs after replay")
        return copied


def _monitoring_evidence_hash(value: R4ResearchControlMonitoringEvidence) -> str:
    return _hash_payload(
        {
            "schema": "research-r4-control-monitoring-evidence.v1",
            "assessment": [
                value.assessment_ref.assessment_id,
                value.assessment_ref.assessment_hash,
            ],
            "owners": [
                value.active_decision.content_hash,
                value.portfolio_result.content_hash,
                value.current_r3_attestation.content_hash,
                value.policy.content_hash,
                value.period_calendar.content_hash,
            ],
            "observations": [item.content_hash for item in value.observations],
            "latest_period": [
                value.latest_period_id,
                _utc_text(value.latest_period_end),
            ],
            "clocks": [
                _utc_text(value.assessment.evaluated_at),
                _utc_text(value.ledger_recorded_at),
            ],
            "status": value.assessment.status.value,
            "research_only": True,
            "must_not_publish_current": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
    )


@dataclass(frozen=True)
class R4ResearchControlPreflightResult:
    """Read-only gate result that grants no current or execution authority."""

    scope_id: str
    as_of: datetime
    status: R4ResearchControlPreflightStatus
    blocker_codes: tuple[R4ResearchControlBlockerCode, ...]
    active_decision_hash: str | None
    monitoring_assessment_hash: str | None
    portfolio_record_hash: str | None
    r3_attestation_hash: str | None
    monitoring_policy_hash: str | None
    period_calendar_hash: str | None
    observation_hashes: tuple[str, ...]
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R4 research-control result scope_id", maximum=300)
        _require_aware(self.as_of, "R4 research-control result as_of")
        if type(self.status) is not R4ResearchControlPreflightStatus:
            raise TypeError("R4 research-control result status differs")
        if type(self.blocker_codes) is not tuple or self.blocker_codes != tuple(
            sorted(set(self.blocker_codes), key=lambda item: item.value)
        ):
            raise ValueError("R4 research-control blockers are not canonical")
        for item in self.blocker_codes:
            if type(item) is not R4ResearchControlBlockerCode:
                raise TypeError("R4 research-control blocker type differs")
        if (self.status is R4ResearchControlPreflightStatus.BLOCKED) != bool(self.blocker_codes):
            raise ValueError("R4 research-control status and blockers differ")
        for label, value in (
            ("active_decision_hash", self.active_decision_hash),
            ("monitoring_assessment_hash", self.monitoring_assessment_hash),
            ("portfolio_record_hash", self.portfolio_record_hash),
            ("r3_attestation_hash", self.r3_attestation_hash),
            ("monitoring_policy_hash", self.monitoring_policy_hash),
            ("period_calendar_hash", self.period_calendar_hash),
        ):
            if value is not None:
                _require_hash(value, f"R4 research-control result {label}")
        if type(self.observation_hashes) is not tuple:
            raise TypeError("R4 research-control observation hashes must be a tuple")
        for value in self.observation_hashes:
            _require_hash(value, "R4 research-control observation hash")
        if self.observation_hashes != tuple(dict.fromkeys(self.observation_hashes)):
            raise ValueError("R4 research-control observation hashes are not canonical")
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R4 research-control result safety boundary differs")
        object.__setattr__(self, "content_hash", _hash_payload(self._hash_payload()))

    def _hash_payload(self) -> dict[str, object]:
        return {
            "schema": "research-r4-control-preflight-result.v1",
            "scope_id": self.scope_id,
            "as_of": _utc_text(self.as_of),
            "status": self.status.value,
            "blockers": [item.value for item in self.blocker_codes],
            "active_decision_hash": self.active_decision_hash,
            "monitoring_assessment_hash": self.monitoring_assessment_hash,
            "portfolio_record_hash": self.portfolio_record_hash,
            "r3_attestation_hash": self.r3_attestation_hash,
            "monitoring_policy_hash": self.monitoring_policy_hash,
            "period_calendar_hash": self.period_calendar_hash,
            "observation_hashes": list(self.observation_hashes),
            "research_only": True,
            "must_not_publish_current": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }


class R4ResearchControlActivePromotionProvider(Protocol):
    """Canonical server-selected active promotion reader."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_active(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R4PromotionDecisionIdentity | None:
        """Return the active exact decision identity or explicit absence."""


class R4ResearchControlMonitoringProvider(Protocol):
    """Server-selecting latest-complete monitoring assessment reader."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_latest_complete(
        self,
        *,
        active_decision: R4PromotionDecisionIdentity,
        as_of: datetime,
    ) -> R4ResearchControlMonitoringEvidence | None:
        """Select by active decision and complete period, never caller health."""


class R4ResearchControlOwnerGraphProvider(Protocol):
    """Existing six-owner R4 monitoring evaluator exposed as an exact read port."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def execute_evidence(
        self,
        command: EvaluateR4PromotionMonitoringCommand,
    ) -> R4MonitoringEvaluationEvidence:
        """Reread and recompute the complete canonical owner graph."""


class R4ResearchControlUnitOfWork(Protocol):
    """Shared read transaction with its trusted server clock."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared read transaction."""

    def server_now(self) -> datetime:
        """Read the trusted clock from inside the transaction."""


@dataclass(frozen=True)
class _OwnerGraph:
    active_decision: R4PromotionDecisionIdentity | None
    monitoring: R4ResearchControlMonitoringEvidence | None
    owners: R4MonitoringEvaluationEvidence | None


class EvaluateR4ResearchControlPreflight:
    """Double-read canonical owners and emit one non-authoritative review gate."""

    def __init__(
        self,
        *,
        active_promotion_provider: R4ResearchControlActivePromotionProvider,
        monitoring_provider: R4ResearchControlMonitoringProvider,
        owner_graph_provider: R4ResearchControlOwnerGraphProvider,
        unit_of_work: R4ResearchControlUnitOfWork,
    ) -> None:
        self._active_promotion_provider = active_promotion_provider
        self._monitoring_provider = monitoring_provider
        self._owner_graph_provider = owner_graph_provider
        self._unit_of_work = unit_of_work
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise R4ResearchControlUnavailable(
                "R4 research-control unit of work is unavailable"
            ) from error
        if len(set(keys)) != 1:
            raise R4ResearchControlUnavailable(
                "R4 research-control owners use different unit of work identities"
            )
        self._expected_uow_key = keys[0]

    def execute(
        self,
        command: EvaluateR4ResearchControlPreflightCommand,
    ) -> R4ResearchControlPreflightResult:
        """Evaluate the latest exact graph without writes or consumer side effects."""

        self._require_command(command)
        try:
            with self._unit_of_work.atomic():
                self._require_unchanged_uow()
                server_now = self._unit_of_work.server_now()
                _require_aware(server_now, "R4 research-control server_now")
                self._require_unchanged_uow()
                if command.as_of > server_now:
                    raise R4ResearchControlUnavailable(
                        "R4 research-control command uses a future as_of"
                    )
                first = self._read_graph(command)
                self._require_unchanged_uow()
                second = self._read_graph(command)
                self._require_unchanged_uow()
        except R4ResearchControlUnavailable:
            raise
        except _UnitOfWorkChanged:
            return self._blocked(command, R4ResearchControlBlockerCode.UNIT_OF_WORK_CHANGED)
        except Exception:
            return self._blocked(
                command,
                R4ResearchControlBlockerCode.OWNER_PROVIDER_UNAVAILABLE,
            )
        if first != second:
            return self._blocked(
                command,
                R4ResearchControlBlockerCode.OWNER_GRAPH_CHANGED_DURING_PREFLIGHT,
                graph=second,
            )
        return self._evaluate_graph(command, second)

    def _read_graph(
        self,
        command: EvaluateR4ResearchControlPreflightCommand,
    ) -> _OwnerGraph:
        self._require_unchanged_uow()
        active = _copy_active(
            self._active_promotion_provider.get_active(
                scope_id=command.scope_id,
                as_of=command.as_of,
            )
        )
        self._require_unchanged_uow()
        if active is None:
            return _OwnerGraph(None, None, None)
        monitoring = _copy_monitoring(
            self._monitoring_provider.get_latest_complete(
                active_decision=active,
                as_of=command.as_of,
            )
        )
        self._require_unchanged_uow()
        if monitoring is None:
            return _OwnerGraph(active, None, None)
        if R4PromotionDecisionIdentity.from_decision(monitoring.active_decision) != active:
            return _OwnerGraph(active, monitoring, None)
        owners = _copy_owner_graph(
            self._owner_graph_provider.execute_evidence(
                EvaluateR4PromotionMonitoringCommand(
                    active_decision=active,
                    policy_id=monitoring.policy.policy_id,
                    policy_version=monitoring.policy.policy_version,
                    expected_policy_hash=monitoring.policy.content_hash,
                    as_of=command.as_of,
                )
            )
        )
        self._require_unchanged_uow()
        return _OwnerGraph(active, monitoring, owners)

    def _evaluate_graph(
        self,
        command: EvaluateR4ResearchControlPreflightCommand,
        graph: _OwnerGraph,
    ) -> R4ResearchControlPreflightResult:
        active = graph.active_decision
        monitoring = graph.monitoring
        owners = graph.owners
        if active is None:
            return self._blocked(
                command,
                R4ResearchControlBlockerCode.ACTIVE_PROMOTION_UNAVAILABLE,
            )
        if monitoring is None:
            return self._blocked(
                command,
                R4ResearchControlBlockerCode.MONITORING_ASSESSMENT_UNAVAILABLE,
                graph=graph,
            )
        if owners is None:
            blocker = (
                R4ResearchControlBlockerCode.OWNER_GRAPH_SUBSTITUTED
                if R4PromotionDecisionIdentity.from_decision(monitoring.active_decision) != active
                else R4ResearchControlBlockerCode.OWNER_GRAPH_UNAVAILABLE
            )
            return self._blocked(command, blocker, graph=graph)
        owner_active = owners.active_decision
        owner_portfolio = owners.portfolio_result
        owner_r3 = owners.current_r3_attestation
        owner_policy = owners.policy
        owner_calendar = owners.period_calendar
        if (
            owner_active is None
            or owner_portfolio is None
            or owner_r3 is None
            or owner_policy is None
            or owner_calendar is None
        ):
            blocker = (
                R4ResearchControlBlockerCode.OWNER_GRAPH_SUBSTITUTED
                if R4PromotionDecisionIdentity.from_decision(monitoring.active_decision) != active
                else R4ResearchControlBlockerCode.OWNER_GRAPH_UNAVAILABLE
            )
            return self._blocked(command, blocker, graph=graph)
        if monitoring.assessment.status is R4MonitoringAssessmentStatus.BREACHED:
            return self._blocked(
                command,
                R4ResearchControlBlockerCode.LATEST_MONITORING_BREACHED,
                graph=graph,
            )
        if monitoring.assessment.status is R4MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED:
            return self._blocked(
                command,
                R4ResearchControlBlockerCode.LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW,
                graph=graph,
            )
        if not (
            active.scope.scope_id == command.scope_id
            and active.recorded_at <= command.as_of < active.valid_until
            and monitoring.assessment.evaluated_at <= monitoring.ledger_recorded_at
            and monitoring.ledger_recorded_at <= command.as_of
            and R4PromotionDecisionIdentity.from_decision(owner_active) == active
            and owner_active == monitoring.active_decision
            and owner_portfolio == monitoring.portfolio_result
            and owner_r3 == monitoring.current_r3_attestation
            and owner_policy == monitoring.policy
            and owner_calendar == monitoring.period_calendar
            and owners.observations == monitoring.observations
            and owners.assessment.evaluated_at == command.as_of
        ):
            return self._blocked(
                command,
                R4ResearchControlBlockerCode.OWNER_GRAPH_SUBSTITUTED,
                graph=graph,
            )
        if owners.assessment.status is not R4MonitoringAssessmentStatus.HEALTHY:
            return self._blocked(
                command,
                R4ResearchControlBlockerCode.OWNER_GRAPH_NOT_HEALTHY,
                graph=graph,
            )
        return R4ResearchControlPreflightResult(
            scope_id=command.scope_id,
            as_of=command.as_of,
            status=(R4ResearchControlPreflightStatus.ELIGIBLE_FOR_MANUAL_CONSUMER_REVIEW),
            blocker_codes=(),
            active_decision_hash=active.content_hash,
            monitoring_assessment_hash=monitoring.assessment.content_hash,
            portfolio_record_hash=monitoring.portfolio_result.content_hash,
            r3_attestation_hash=monitoring.current_r3_attestation.content_hash,
            monitoring_policy_hash=monitoring.policy.content_hash,
            period_calendar_hash=monitoring.period_calendar.content_hash,
            observation_hashes=tuple(item.content_hash for item in monitoring.observations),
        )

    @staticmethod
    def _blocked(
        command: EvaluateR4ResearchControlPreflightCommand,
        blocker: R4ResearchControlBlockerCode,
        *,
        graph: _OwnerGraph | None = None,
    ) -> R4ResearchControlPreflightResult:
        active = None if graph is None else graph.active_decision
        monitoring = None if graph is None else graph.monitoring
        return R4ResearchControlPreflightResult(
            scope_id=command.scope_id,
            as_of=command.as_of,
            status=R4ResearchControlPreflightStatus.BLOCKED,
            blocker_codes=(blocker,),
            active_decision_hash=None if active is None else active.content_hash,
            monitoring_assessment_hash=(
                None if monitoring is None else monitoring.assessment.content_hash
            ),
            portfolio_record_hash=(
                None if monitoring is None else monitoring.portfolio_result.content_hash
            ),
            r3_attestation_hash=(
                None if monitoring is None else monitoring.current_r3_attestation.content_hash
            ),
            monitoring_policy_hash=(None if monitoring is None else monitoring.policy.content_hash),
            period_calendar_hash=(
                None if monitoring is None else monitoring.period_calendar.content_hash
            ),
            observation_hashes=(
                ()
                if monitoring is None
                else tuple(item.content_hash for item in monitoring.observations)
            ),
        )

    @staticmethod
    def _require_command(command: object) -> None:
        try:
            if type(command) is not EvaluateR4ResearchControlPreflightCommand:
                raise TypeError
            EvaluateR4ResearchControlPreflightCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R4ResearchControlUnavailable(
                "R4 research-control command is malformed"
            ) from error

    def _current_uow_keys(self) -> tuple[str, ...]:
        values: tuple[object, ...] = (
            self._active_promotion_provider.unit_of_work_key,
            self._monitoring_provider.unit_of_work_key,
            self._owner_graph_provider.unit_of_work_key,
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


def _copy_active(value: object) -> R4PromotionDecisionIdentity | None:
    if value is None:
        return None
    if type(value) is not R4PromotionDecisionIdentity:
        raise TypeError("R4 research-control active provider returned another type")
    copied = deepcopy(value)
    if type(copied) is not R4PromotionDecisionIdentity:
        raise TypeError("R4 research-control active copy returned another type")
    R4PromotionDecisionIdentity.__post_init__(copied)
    if copied != value:
        raise ValueError("R4 research-control active decision was substituted")
    return copied


def _copy_monitoring(value: object) -> R4ResearchControlMonitoringEvidence | None:
    if value is None:
        return None
    if type(value) is not R4ResearchControlMonitoringEvidence:
        raise TypeError("R4 research-control monitoring provider returned another type")
    candidate = deepcopy(value)
    if type(candidate) is not R4ResearchControlMonitoringEvidence:
        raise TypeError("R4 research-control monitoring copy returned another type")
    copied = candidate.validated_copy()
    if copied != candidate or candidate != value:
        raise ValueError("R4 research-control monitoring evidence was substituted")
    return copied


def _copy_owner_graph(value: object) -> R4MonitoringEvaluationEvidence:
    if type(value) is not R4MonitoringEvaluationEvidence:
        raise TypeError("R4 research-control owner graph provider returned another type")
    candidate = deepcopy(value)
    if type(candidate) is not R4MonitoringEvaluationEvidence:
        raise TypeError("R4 research-control owner graph copy returned another type")
    assessment = candidate.assessment
    if type(assessment) is not R4MonitoringAssessment:
        raise TypeError("R4 research-control owner assessment type differs")
    replayed = _replay_assessment(
        active_decision=candidate.active_decision,
        portfolio_result=candidate.portfolio_result,
        current_r3_attestation=candidate.current_r3_attestation,
        policy=candidate.policy,
        period_calendar=candidate.period_calendar,
        observations=candidate.observations,
        assessment=assessment,
    )
    if replayed != assessment:
        raise ValueError("R4 research-control owner graph differs after replay")
    if candidate != value:
        raise ValueError("R4 research-control owner graph was substituted during copy")
    return R4MonitoringEvaluationEvidence(
        active_decision=candidate.active_decision,
        portfolio_result=candidate.portfolio_result,
        current_r3_attestation=candidate.current_r3_attestation,
        policy=candidate.policy,
        period_calendar=candidate.period_calendar,
        observations=candidate.observations,
        assessment=replayed,
    )


def _replay_assessment(
    *,
    active_decision: R4PromotionDecision | None,
    portfolio_result: R4PromotionPortfolioRecordSeal | None,
    current_r3_attestation: R4PromotionR3AttestationEvidence | None,
    policy: R4MonitoringPolicy | None,
    period_calendar: R4MonitoringPeriodCalendar | None,
    observations: tuple[R4MonitoringObservation, ...],
    assessment: R4MonitoringAssessment,
) -> R4MonitoringAssessment:
    if type(observations) is not tuple or any(
        type(item) is not R4MonitoringObservation for item in observations
    ):
        raise TypeError("R4 research-control observations type differs")
    R4MonitoringAssessment.__post_init__(assessment)
    return evaluate_r4_promotion_monitoring(
        requested_active_decision=assessment.active_decision,
        requested_policy_id=assessment.requested_policy_id,
        requested_policy_version=assessment.requested_policy_version,
        expected_policy_hash=assessment.expected_policy_hash,
        active_decision=active_decision,
        portfolio_result=portfolio_result,
        current_r3_attestation=current_r3_attestation,
        policy=policy,
        period_calendar=period_calendar,
        observations=observations,
        evaluated_at=assessment.evaluated_at,
    )


def _require_monitoring_evidence_types(
    value: R4ResearchControlMonitoringEvidence,
) -> None:
    expected: tuple[tuple[object, type[object], str], ...] = (
        (value.assessment_ref, R4MonitoringAssessmentRef, "assessment reference"),
        (value.active_decision, R4PromotionDecision, "active decision"),
        (value.portfolio_result, R4PromotionPortfolioRecordSeal, "portfolio result"),
        (
            value.current_r3_attestation,
            R4PromotionR3AttestationEvidence,
            "R3 attestation",
        ),
        (value.policy, R4MonitoringPolicy, "monitoring policy"),
        (value.period_calendar, R4MonitoringPeriodCalendar, "period calendar"),
        (value.assessment, R4MonitoringAssessment, "assessment"),
    )
    for candidate, expected_type, label in expected:
        if type(candidate) is not expected_type:
            raise TypeError(f"R4 research-control {label} type differs")
    R4MonitoringAssessmentRef.__post_init__(value.assessment_ref)
    R4PromotionDecision.__post_init__(value.active_decision)
    R4PromotionPortfolioRecordSeal.__post_init__(value.portfolio_result)
    R4PromotionR3AttestationEvidence.__post_init__(value.current_r3_attestation)
    R4MonitoringPolicy.__post_init__(value.policy)
    R4MonitoringPeriodCalendar.__post_init__(value.period_calendar)
    for observation in value.observations:
        R4MonitoringObservation.__post_init__(observation)
    _require_hash(value.latest_period_id, "R4 research-control latest_period_id")
    _require_aware(value.latest_period_end, "R4 research-control latest_period_end")


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError("R4 research-control unit_of_work_key must be an exact string")
    return value


def _require_token(value: object, label: str, *, maximum: int = 192) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be an exact bounded token")


def _require_hash(value: object, label: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{label} must be an exact SHA-256 digest")


def _require_aware(value: object, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


__all__ = [
    "EvaluateR4ResearchControlPreflight",
    "EvaluateR4ResearchControlPreflightCommand",
    "R4ResearchControlActivePromotionProvider",
    "R4ResearchControlBlockerCode",
    "R4ResearchControlMonitoringEvidence",
    "R4ResearchControlMonitoringProvider",
    "R4ResearchControlOwnerGraphProvider",
    "R4ResearchControlPreflightResult",
    "R4ResearchControlPreflightStatus",
    "R4ResearchControlUnavailable",
    "R4ResearchControlUnitOfWork",
]
