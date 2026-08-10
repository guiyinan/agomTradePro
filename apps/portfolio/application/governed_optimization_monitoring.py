"""ID-only orchestration for governed R8 post-promotion monitoring."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

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
    OptimizationMonitoringPeriodObservation,
    OptimizationMonitoringSourceEvidence,
    OptimizationPromotionSelector,
    evaluate_governed_optimization_monitoring,
)
from apps.portfolio.domain.optimization_input_receipt import (
    GovernedOptimizationInputReceipt,
)


class GovernedOptimizationMonitoringUnavailable(RuntimeError):
    """Exact monitoring owner graph or trusted clock is unavailable."""


class GovernedOptimizationMonitoringClock(Protocol):
    """Trusted non-caller clock for as-of causality."""

    def now(self) -> datetime:
        """Return a timezone-aware trusted clock value."""


class GovernedOptimizationMonitoringUnitOfWork(Protocol):
    """Shared transaction identity for every exact owner read."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact shared transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one atomic owner-read boundary."""


class _UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the exact shared transaction identity."""


class ActiveOptimizationResultProvider(_UnitOfWorkBound, Protocol):
    """Exact active lifecycle result provider."""

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_result_hash: str,
        promotion_event_id: str,
        expected_promotion_event_hash: str,
        as_of: datetime,
    ) -> ActiveGovernedOptimizationResultEvidence | None:
        """Return a full active lifecycle projection or None."""


class OptimizationInputReceiptProvider(_UnitOfWorkBound, Protocol):
    """Exact independent input receipt provider."""

    def get_exact(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_receipt_hash: str,
        as_of: datetime,
    ) -> GovernedOptimizationInputReceipt | None:
        """Return one exact receipt or None."""


class UpstreamOptimizationPromotionProvider(_UnitOfWorkBound, Protocol):
    """Exact current R3, R4, or R5 Promotion provider."""

    def get_exact(
        self,
        *,
        selector: OptimizationPromotionSelector,
        as_of: datetime,
    ) -> ExactPromotionAttestation | None:
        """Return one exact active Promotion or None."""


class OptimizationMonitoringPolicyProvider(_UnitOfWorkBound, Protocol):
    """Research-owned exact monitoring policy provider."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        as_of: datetime,
    ) -> GovernedOptimizationMonitoringPolicy | None:
        """Return one exact active policy or None."""


class OptimizationMonitoringCalendarProvider(_UnitOfWorkBound, Protocol):
    """Portfolio-owned exact period-calendar provider."""

    def get_exact(
        self,
        *,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> GovernedOptimizationMonitoringCalendar | None:
        """Return the exact full period membership or None."""


class OptimizationMonitoringFeedbackProvider(_UnitOfWorkBound, Protocol):
    """Exact Portfolio or Broker feedback provider."""

    def list_exact(
        self,
        *,
        result_id: str,
        result_hash: str,
        receipt_id: str,
        receipt_hash: str,
        calendar_id: str,
        calendar_hash: str,
        period_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[OptimizationMonitoringSourceEvidence, ...]:
        """Return exact owner feedback for every period."""


class OptimizationMonitoringRawFactProvider(_UnitOfWorkBound, Protocol):
    """Exact typed raw-fact provider."""

    def list_exact(
        self,
        *,
        result_id: str,
        result_hash: str,
        receipt_id: str,
        receipt_hash: str,
        policy_id: str,
        policy_hash: str,
        calendar_id: str,
        calendar_hash: str,
        period_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[OptimizationMonitoringPeriodObservation, ...]:
        """Return complete raw observations for every period."""


@dataclass(frozen=True)
class EvaluateGovernedOptimizationMonitoringCommand:
    """Identity-only request without caller facts, policy, clocks, or outcomes."""

    policy_id: str
    policy_version: str
    expected_policy_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Require exact canonical selectors and one timezone-aware as-of."""

        for label, value in (
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
        ):
            require_token(value, f"monitoring command {label}")
        require_sha256(self.expected_policy_hash, "monitoring command expected_policy_hash")
        require_aware(self.as_of, "monitoring command as_of")


@dataclass(frozen=True)
class _MonitoringOwnerGraph:
    active_result: ActiveGovernedOptimizationResultEvidence | None
    receipt: GovernedOptimizationInputReceipt | None
    upstream_promotions: tuple[ExactPromotionAttestation, ...]
    policy: GovernedOptimizationMonitoringPolicy | None
    calendar: GovernedOptimizationMonitoringCalendar | None
    portfolio_evidence: tuple[OptimizationMonitoringSourceEvidence, ...]
    broker_evidence: tuple[OptimizationMonitoringSourceEvidence, ...]
    observations: tuple[OptimizationMonitoringPeriodObservation, ...]


@dataclass(frozen=True)
class GovernedOptimizationMonitoringEvaluationEvidence:
    """Complete owner reread graph plus its locally recomputed assessment."""

    active_result: ActiveGovernedOptimizationResultEvidence | None
    receipt: GovernedOptimizationInputReceipt | None
    upstream_promotions: tuple[ExactPromotionAttestation, ...]
    policy: GovernedOptimizationMonitoringPolicy | None
    calendar: GovernedOptimizationMonitoringCalendar | None
    portfolio_evidence: tuple[OptimizationMonitoringSourceEvidence, ...]
    broker_evidence: tuple[OptimizationMonitoringSourceEvidence, ...]
    observations: tuple[OptimizationMonitoringPeriodObservation, ...]
    assessment: GovernedOptimizationMonitoringAssessment


class EvaluateGovernedOptimizationMonitoring:
    """Reread every exact owner twice and return a research-only assessment."""

    def __init__(
        self,
        *,
        active_result_provider: ActiveOptimizationResultProvider,
        receipt_provider: OptimizationInputReceiptProvider,
        r3_promotion_provider: UpstreamOptimizationPromotionProvider,
        r4_promotion_provider: UpstreamOptimizationPromotionProvider,
        r5_promotion_provider: UpstreamOptimizationPromotionProvider,
        policy_provider: OptimizationMonitoringPolicyProvider,
        calendar_provider: OptimizationMonitoringCalendarProvider,
        portfolio_feedback_provider: OptimizationMonitoringFeedbackProvider,
        broker_feedback_provider: OptimizationMonitoringFeedbackProvider,
        raw_fact_provider: OptimizationMonitoringRawFactProvider,
        unit_of_work: GovernedOptimizationMonitoringUnitOfWork,
        clock: GovernedOptimizationMonitoringClock,
    ) -> None:
        self._active_result_provider = active_result_provider
        self._receipt_provider = receipt_provider
        self._promotion_providers = {
            "r3": r3_promotion_provider,
            "r4": r4_promotion_provider,
            "r5": r5_promotion_provider,
        }
        self._policy_provider = policy_provider
        self._calendar_provider = calendar_provider
        self._portfolio_feedback_provider = portfolio_feedback_provider
        self._broker_feedback_provider = broker_feedback_provider
        self._raw_fact_provider = raw_fact_provider
        self._unit_of_work = unit_of_work
        self._clock = clock
        try:
            keys = self._current_uow_keys()
        except Exception as exc:
            raise GovernedOptimizationMonitoringUnavailable(
                "R8 monitoring UoW identity is unavailable"
            ) from exc
        if len(keys) != 1:
            raise GovernedOptimizationMonitoringUnavailable(
                "R8 monitoring owners use different units of work"
            )
        self._expected_uow_key = next(iter(keys))

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact owner-read transaction identity."""

        self._require_unchanged_uow()
        return self._expected_uow_key

    def execute(
        self,
        command: EvaluateGovernedOptimizationMonitoringCommand,
    ) -> GovernedOptimizationMonitoringAssessment:
        """Evaluate without lifecycle, transition, current, or execution side effects."""

        return self.execute_evidence(command).assessment

    def execute_evidence(
        self,
        command: EvaluateGovernedOptimizationMonitoringCommand,
    ) -> GovernedOptimizationMonitoringEvaluationEvidence:
        """Return the exact double-read owner graph and derived assessment."""

        try:
            if type(command) is not EvaluateGovernedOptimizationMonitoringCommand:
                raise TypeError("monitoring command type is invalid")
            EvaluateGovernedOptimizationMonitoringCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GovernedOptimizationMonitoringUnavailable(
                "R8 monitoring command is invalid"
            ) from exc
        try:
            server_now = self._clock.now()
            require_aware(server_now, "R8 monitoring trusted clock")
        except Exception as exc:
            raise GovernedOptimizationMonitoringUnavailable(
                "trusted R8 monitoring clock is unavailable"
            ) from exc
        if command.as_of > server_now:
            raise GovernedOptimizationMonitoringUnavailable(
                "future R8 monitoring as_of is forbidden"
            )
        self._require_unchanged_uow()
        try:
            with self._unit_of_work.atomic():
                self._require_unchanged_uow()
                first = self._read_owner_graph(command)
                self._require_unchanged_uow()
                assessment = self._evaluate(command, first)
                GovernedOptimizationMonitoringAssessment.__post_init__(assessment)
                if first.policy is not None and first.calendar is not None:
                    assessment = assessment.validated_copy(
                        policy=first.policy,
                        calendar=first.calendar,
                        observations=first.observations,
                    )
                self._require_unchanged_uow()
                second = self._read_owner_graph(command)
                self._require_unchanged_uow()
                if second != first:
                    raise GovernedOptimizationMonitoringUnavailable(
                        "R8 monitoring owner graph changed during evaluation"
                    )
                GovernedOptimizationMonitoringAssessment.__post_init__(assessment)
                if second.policy is not None and second.calendar is not None:
                    assessment = assessment.validated_copy(
                        policy=second.policy,
                        calendar=second.calendar,
                        observations=second.observations,
                    )
                return GovernedOptimizationMonitoringEvaluationEvidence(
                    active_result=second.active_result,
                    receipt=second.receipt,
                    upstream_promotions=second.upstream_promotions,
                    policy=second.policy,
                    calendar=second.calendar,
                    portfolio_evidence=second.portfolio_evidence,
                    broker_evidence=second.broker_evidence,
                    observations=second.observations,
                    assessment=assessment,
                )
        except GovernedOptimizationMonitoringUnavailable:
            raise
        except Exception as exc:
            raise GovernedOptimizationMonitoringUnavailable(
                "R8 monitoring owner graph is unavailable"
            ) from exc

    def _read_owner_graph(
        self,
        command: EvaluateGovernedOptimizationMonitoringCommand,
    ) -> _MonitoringOwnerGraph:
        policy = self._policy_provider.get_exact(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            as_of=command.as_of,
        )
        if policy is not None and type(policy) is not GovernedOptimizationMonitoringPolicy:
            raise TypeError("policy provider returned an invalid type")
        if policy is None:
            return _MonitoringOwnerGraph(None, None, (), None, None, (), (), ())
        GovernedOptimizationMonitoringPolicy.__post_init__(policy)
        target = policy.target
        active = self._active_result_provider.get_exact(
            result_id=target.result_id,
            result_version=target.result_version,
            expected_result_hash=target.result_hash,
            promotion_event_id=target.r8_promotion_event_id,
            expected_promotion_event_hash=target.r8_promotion_event_hash,
            as_of=command.as_of,
        )
        if active is not None and type(active) is not ActiveGovernedOptimizationResultEvidence:
            raise TypeError("active result provider returned an invalid type")
        receipt = self._receipt_provider.get_exact(
            receipt_id=target.receipt_id,
            receipt_version=target.receipt_version,
            expected_receipt_hash=target.receipt_hash,
            as_of=command.as_of,
        )
        if receipt is not None and type(receipt) is not GovernedOptimizationInputReceipt:
            raise TypeError("receipt provider returned an invalid type")
        promotions: list[ExactPromotionAttestation] = []
        for selector in target.upstream_promotions:
            promotion = self._promotion_providers[selector.capability_key].get_exact(
                selector=selector,
                as_of=command.as_of,
            )
            if promotion is not None:
                if type(promotion) is not ExactPromotionAttestation:
                    raise TypeError("Promotion provider returned an invalid type")
                promotions.append(promotion)
        calendar: GovernedOptimizationMonitoringCalendar | None = None
        portfolio: tuple[OptimizationMonitoringSourceEvidence, ...] = ()
        broker: tuple[OptimizationMonitoringSourceEvidence, ...] = ()
        observations: tuple[OptimizationMonitoringPeriodObservation, ...] = ()
        if policy is not None:
            calendar = self._calendar_provider.get_exact(
                calendar_id=policy.calendar_id,
                calendar_version=policy.calendar_version,
                expected_calendar_hash=policy.calendar_hash,
                as_of=command.as_of,
            )
            if (
                calendar is not None
                and type(calendar) is not GovernedOptimizationMonitoringCalendar
            ):
                raise TypeError("calendar provider returned an invalid type")
        if calendar is not None:
            period_ids = tuple(item.period_id for item in calendar.periods)
            portfolio = self._portfolio_feedback_provider.list_exact(
                result_id=target.result_id,
                result_hash=target.result_hash,
                receipt_id=target.receipt_id,
                receipt_hash=target.receipt_hash,
                calendar_id=calendar.calendar_id,
                calendar_hash=calendar.content_hash,
                period_ids=period_ids,
                as_of=command.as_of,
            )
            broker = self._broker_feedback_provider.list_exact(
                result_id=target.result_id,
                result_hash=target.result_hash,
                receipt_id=target.receipt_id,
                receipt_hash=target.receipt_hash,
                calendar_id=calendar.calendar_id,
                calendar_hash=calendar.content_hash,
                period_ids=period_ids,
                as_of=command.as_of,
            )
            observations = self._raw_fact_provider.list_exact(
                result_id=target.result_id,
                result_hash=target.result_hash,
                receipt_id=target.receipt_id,
                receipt_hash=target.receipt_hash,
                calendar_id=calendar.calendar_id,
                calendar_hash=calendar.content_hash,
                period_ids=period_ids,
                as_of=command.as_of,
                policy_id=command.policy_id,
                policy_hash=command.expected_policy_hash,
            )
            if type(portfolio) is not tuple or any(
                type(item) is not OptimizationMonitoringSourceEvidence for item in portfolio
            ):
                raise TypeError("Portfolio feedback provider returned an invalid type")
            if type(broker) is not tuple or any(
                type(item) is not OptimizationMonitoringSourceEvidence for item in broker
            ):
                raise TypeError("Broker feedback provider returned an invalid type")
            if type(observations) is not tuple or any(
                type(item) is not OptimizationMonitoringPeriodObservation for item in observations
            ):
                raise TypeError("raw-fact provider returned an invalid type")
        return _MonitoringOwnerGraph(
            active_result=active,
            receipt=receipt,
            upstream_promotions=tuple(promotions),
            policy=policy,
            calendar=calendar,
            portfolio_evidence=portfolio,
            broker_evidence=broker,
            observations=observations,
        )

    @staticmethod
    def _evaluate(
        command: EvaluateGovernedOptimizationMonitoringCommand,
        graph: _MonitoringOwnerGraph,
    ) -> GovernedOptimizationMonitoringAssessment:
        return evaluate_governed_optimization_monitoring(
            requested_policy_id=command.policy_id,
            requested_policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            active_result=graph.active_result,
            receipt=graph.receipt,
            current_upstream_promotions=graph.upstream_promotions,
            policy=graph.policy,
            calendar=graph.calendar,
            portfolio_evidence=graph.portfolio_evidence,
            broker_evidence=graph.broker_evidence,
            observations=graph.observations,
            evaluated_at=command.as_of,
        )

    def _current_uow_keys(self) -> set[str]:
        providers: tuple[_UnitOfWorkBound, ...] = (
            self._active_result_provider,
            self._receipt_provider,
            *self._promotion_providers.values(),
            self._policy_provider,
            self._calendar_provider,
            self._portfolio_feedback_provider,
            self._broker_feedback_provider,
            self._raw_fact_provider,
            self._unit_of_work,
        )
        return {_provider_uow_key(provider) for provider in providers}

    def _require_unchanged_uow(self) -> None:
        try:
            keys = self._current_uow_keys()
        except Exception as exc:
            raise GovernedOptimizationMonitoringUnavailable(
                "R8 monitoring UoW identity is unavailable"
            ) from exc
        if keys != {self._expected_uow_key}:
            raise GovernedOptimizationMonitoringUnavailable("R8 monitoring UoW identity changed")


def _provider_uow_key(provider: _UnitOfWorkBound) -> str:
    key = provider.unit_of_work_key
    if type(key) is not str or not key.strip():
        raise ValueError("R8 monitoring provider UoW key is invalid")
    return key


__all__ = [
    "ActiveOptimizationResultProvider",
    "EvaluateGovernedOptimizationMonitoring",
    "EvaluateGovernedOptimizationMonitoringCommand",
    "GovernedOptimizationMonitoringClock",
    "GovernedOptimizationMonitoringEvaluationEvidence",
    "GovernedOptimizationMonitoringUnavailable",
    "GovernedOptimizationMonitoringUnitOfWork",
    "OptimizationInputReceiptProvider",
    "OptimizationMonitoringCalendarProvider",
    "OptimizationMonitoringFeedbackProvider",
    "OptimizationMonitoringPolicyProvider",
    "OptimizationMonitoringRawFactProvider",
    "OptimizationPromotionSelector",
    "UpstreamOptimizationPromotionProvider",
]
