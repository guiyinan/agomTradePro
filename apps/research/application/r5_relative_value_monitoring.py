"""Identity-only orchestration for R5 post-promotion monitoring Phase A."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.r5_relative_value_monitoring import (
    R5PostPromotionMonitoringAssessment,
    evaluate_r5_post_promotion_monitoring,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringCalendar,
    R5MonitoringFixedIncomeEvidence,
    R5MonitoringPolicy,
    _require_aware,
    _require_hash,
    _require_token,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5PostPromotionMonitoringFact,
)


class R5PostPromotionMonitoringUnavailable(RuntimeError):
    """A trusted clock, UoW, or authoritative owner could not answer exactly."""


class R5MonitoringClock(Protocol):
    """Trusted server-side monitoring clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server time."""


class R5MonitoringUnitOfWork(Protocol):
    """Shared transaction boundary for every owner provider."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact shared boundary identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the common owner-read transaction."""


class _UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the exact shared boundary identity."""


class R5MonitoringPolicyProvider(_UnitOfWorkBound, Protocol):
    """Authoritative Research monitoring-policy provider."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        as_of: datetime,
    ) -> R5MonitoringPolicy | None:
        """Return the exact policy selected only by identity."""


class R5MonitoringActiveLifecycleProvider(_UnitOfWorkBound, Protocol):
    """Authoritative active R5 lifecycle provider."""

    def get_exact(
        self,
        *,
        scope_id: str,
        scope_hash: str,
        decision_id: str,
        decision_version: str,
        expected_decision_hash: str,
        expected_lifecycle_hash: str,
        as_of: datetime,
    ) -> R5MonitoringActiveLifecycle | None:
        """Return the exact active lifecycle projection."""


class R5MonitoringCalendarProvider(_UnitOfWorkBound, Protocol):
    """Authoritative canonical period-calendar provider."""

    def get_exact(
        self,
        *,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        as_of: datetime,
    ) -> R5MonitoringCalendar | None:
        """Return the exact complete calendar."""


class R5MonitoringFixedIncomeProvider(_UnitOfWorkBound, Protocol):
    """Authoritative fixed-income result and owner-seal provider."""

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_result_hash: str,
        owner_seal_id: str,
        owner_seal_version: str,
        expected_owner_seal_hash: str,
        as_of: datetime,
    ) -> R5MonitoringFixedIncomeEvidence | None:
        """Return the exact fixed-income projection."""


class R5MonitoringPortfolioFactProvider(_UnitOfWorkBound, Protocol):
    """Authoritative independent Portfolio monitoring-fact provider."""

    def list_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        target_hash: str,
        calendar_id: str,
        calendar_version: str,
        expected_calendar_hash: str,
        period_ids: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[R5PostPromotionMonitoringFact, ...]:
        """Return one exact fact for every canonical period member."""


@dataclass(frozen=True)
class EvaluateR5PostPromotionMonitoringCommand:
    """Identity-only command carrying no facts, owner objects, or outcomes."""

    policy_id: str
    policy_version: str
    expected_policy_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "R5 monitoring command policy_id")
        _require_token(self.policy_version, "R5 monitoring command policy_version")
        _require_hash(self.expected_policy_hash, "R5 monitoring command policy hash")
        _require_aware(self.as_of, "R5 monitoring command as_of")


@dataclass(frozen=True)
class R5MonitoringOwnerGraph:
    """One deeply copied owner graph read inside the shared UoW."""

    policy: R5MonitoringPolicy | None
    active_lifecycle: R5MonitoringActiveLifecycle | None
    calendar: R5MonitoringCalendar | None
    fixed_income: R5MonitoringFixedIncomeEvidence | None
    portfolio_facts: tuple[R5PostPromotionMonitoringFact, ...]


class EvaluateR5PostPromotionMonitoring:
    """Reread every owner twice and recompute one research-only assessment."""

    def __init__(
        self,
        *,
        policy_provider: R5MonitoringPolicyProvider,
        active_lifecycle_provider: R5MonitoringActiveLifecycleProvider,
        calendar_provider: R5MonitoringCalendarProvider,
        fixed_income_provider: R5MonitoringFixedIncomeProvider,
        portfolio_fact_provider: R5MonitoringPortfolioFactProvider,
        unit_of_work: R5MonitoringUnitOfWork,
        clock: R5MonitoringClock,
    ) -> None:
        self._policy_provider = policy_provider
        self._active_lifecycle_provider = active_lifecycle_provider
        self._calendar_provider = calendar_provider
        self._fixed_income_provider = fixed_income_provider
        self._portfolio_fact_provider = portfolio_fact_provider
        self._unit_of_work = unit_of_work
        self._clock = clock
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise R5PostPromotionMonitoringUnavailable(
                "R5 monitoring UoW identity is unavailable"
            ) from error
        if len(set(keys)) != 1:
            raise R5PostPromotionMonitoringUnavailable("R5 monitoring owners use different UoWs")
        self._expected_uow_key = keys[0]

    def execute(
        self,
        command: EvaluateR5PostPromotionMonitoringCommand,
    ) -> R5PostPromotionMonitoringAssessment:
        """Validate the command and trusted cutoff, then double-read all owners."""

        try:
            if type(command) is not EvaluateR5PostPromotionMonitoringCommand:
                raise TypeError
            command.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise R5PostPromotionMonitoringUnavailable(
                "R5 monitoring command is invalid"
            ) from error
        try:
            server_now = self._clock.now()
            _require_aware(server_now, "R5 monitoring trusted server clock")
        except Exception as error:
            raise R5PostPromotionMonitoringUnavailable(
                "R5 monitoring trusted clock is unavailable"
            ) from error
        if command.as_of > server_now:
            raise R5PostPromotionMonitoringUnavailable("R5 monitoring command uses a future as_of")
        self._require_unchanged_uow()
        try:
            with self._unit_of_work.atomic():
                self._require_unchanged_uow()
                first = self._read_owner_graph(command)
                self._require_unchanged_uow()
                first_assessment = self._evaluate(command, first)
                self._require_unchanged_uow()
                second = self._read_owner_graph(command)
                self._require_unchanged_uow()
                if second != first:
                    raise R5PostPromotionMonitoringUnavailable(
                        "R5 monitoring owner graph changed during evaluation"
                    )
                second_assessment = self._evaluate(command, second)
                if second_assessment != first_assessment:
                    raise R5PostPromotionMonitoringUnavailable(
                        "R5 monitoring assessment changed during evaluation"
                    )
                return second_assessment
        except R5PostPromotionMonitoringUnavailable:
            raise
        except Exception as error:
            raise R5PostPromotionMonitoringUnavailable(
                "R5 monitoring owner graph is unavailable"
            ) from error

    def _read_owner_graph(
        self,
        command: EvaluateR5PostPromotionMonitoringCommand,
    ) -> R5MonitoringOwnerGraph:
        policy_value = self._policy_provider.get_exact(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            as_of=command.as_of,
        )
        policy = _copy_policy(policy_value)
        if policy is None:
            return R5MonitoringOwnerGraph(None, None, None, None, ())
        target = policy.target
        active = _copy_active(
            self._active_lifecycle_provider.get_exact(
                scope_id=target.active_lifecycle.scope_id,
                scope_hash=target.active_lifecycle.scope_hash,
                decision_id=target.active_lifecycle.decision_id,
                decision_version=target.active_lifecycle.decision_version,
                expected_decision_hash=target.active_lifecycle.decision_hash,
                expected_lifecycle_hash=target.active_lifecycle.content_hash,
                as_of=command.as_of,
            )
        )
        calendar = _copy_calendar(
            self._calendar_provider.get_exact(
                calendar_id=policy.calendar_owner.owner_id,
                calendar_version=policy.calendar_owner.owner_version,
                expected_calendar_hash=policy.calendar_hash,
                as_of=command.as_of,
            )
        )
        fixed_income = _copy_fixed_income(
            self._fixed_income_provider.get_exact(
                result_id=target.fixed_income.result_id,
                result_version=target.fixed_income.result_version,
                expected_result_hash=target.fixed_income.result_hash,
                owner_seal_id=target.fixed_income.owner_seal_id,
                owner_seal_version=target.fixed_income.owner_seal_version,
                expected_owner_seal_hash=target.fixed_income.owner_seal_hash,
                as_of=command.as_of,
            )
        )
        facts: tuple[R5PostPromotionMonitoringFact, ...] = ()
        if calendar is not None:
            raw_facts = self._portfolio_fact_provider.list_exact(
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                expected_policy_hash=policy.content_hash,
                target_hash=target.content_hash,
                calendar_id=calendar.owner.owner_id,
                calendar_version=calendar.owner.owner_version,
                expected_calendar_hash=calendar.content_hash,
                period_ids=tuple(item.period_id for item in calendar.entries),
                as_of=command.as_of,
            )
            if type(raw_facts) is not tuple:
                raise TypeError("Portfolio monitoring provider returned a non-tuple")
            facts = tuple(_copy_fact(item) for item in raw_facts)
        return R5MonitoringOwnerGraph(policy, active, calendar, fixed_income, facts)

    @staticmethod
    def _evaluate(
        command: EvaluateR5PostPromotionMonitoringCommand,
        graph: R5MonitoringOwnerGraph,
    ) -> R5PostPromotionMonitoringAssessment:
        assessment = evaluate_r5_post_promotion_monitoring(
            requested_policy_id=command.policy_id,
            requested_policy_version=command.policy_version,
            expected_policy_hash=command.expected_policy_hash,
            active_lifecycle=graph.active_lifecycle,
            fixed_income=graph.fixed_income,
            policy=graph.policy,
            calendar=graph.calendar,
            portfolio_facts=graph.portfolio_facts,
            evaluated_at=command.as_of,
        )
        if (
            graph.policy is not None
            and graph.calendar is not None
            and graph.active_lifecycle == graph.policy.target.active_lifecycle
            and graph.fixed_income == graph.policy.target.fixed_income
        ):
            return assessment.validated_copy(
                policy=graph.policy,
                calendar=graph.calendar,
                facts=graph.portfolio_facts,
            )
        return assessment

    def _current_uow_keys(self) -> tuple[str, ...]:
        values: tuple[object, ...] = (
            self._policy_provider.unit_of_work_key,
            self._active_lifecycle_provider.unit_of_work_key,
            self._calendar_provider.unit_of_work_key,
            self._fixed_income_provider.unit_of_work_key,
            self._portfolio_fact_provider.unit_of_work_key,
            self._unit_of_work.unit_of_work_key,
        )
        return tuple(_exact_uow_key(value) for value in values)

    def _require_unchanged_uow(self) -> None:
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise R5PostPromotionMonitoringUnavailable(
                "R5 monitoring UoW identity is unavailable"
            ) from error
        if any(value != self._expected_uow_key for value in keys):
            raise R5PostPromotionMonitoringUnavailable("R5 monitoring UoW identity changed")


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError("R5 monitoring UoW key must be an exact non-blank string")
    return value


def _copy_policy(value: object) -> R5MonitoringPolicy | None:
    if value is None:
        return None
    if type(value) is not R5MonitoringPolicy:
        raise TypeError("policy provider returned an invalid object")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("policy provider returned a substituted object")
    return copied


def _copy_active(value: object) -> R5MonitoringActiveLifecycle | None:
    if value is None:
        return None
    if type(value) is not R5MonitoringActiveLifecycle:
        raise TypeError("active lifecycle provider returned an invalid object")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("active lifecycle provider returned a substituted object")
    return copied


def _copy_calendar(value: object) -> R5MonitoringCalendar | None:
    if value is None:
        return None
    if type(value) is not R5MonitoringCalendar:
        raise TypeError("calendar provider returned an invalid object")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("calendar provider returned a substituted object")
    return copied


def _copy_fixed_income(value: object) -> R5MonitoringFixedIncomeEvidence | None:
    if value is None:
        return None
    if type(value) is not R5MonitoringFixedIncomeEvidence:
        raise TypeError("fixed-income provider returned an invalid object")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("fixed-income provider returned a substituted object")
    return copied


def _copy_fact(value: object) -> R5PostPromotionMonitoringFact:
    if type(value) is not R5PostPromotionMonitoringFact:
        raise TypeError("Portfolio fact provider returned an invalid object")
    copied = value.validated_copy()
    if copied != value:
        raise ValueError("Portfolio fact provider returned a substituted object")
    return copied


__all__ = [
    "EvaluateR5PostPromotionMonitoring",
    "EvaluateR5PostPromotionMonitoringCommand",
    "R5MonitoringActiveLifecycleProvider",
    "R5MonitoringCalendarProvider",
    "R5MonitoringClock",
    "R5MonitoringFixedIncomeProvider",
    "R5MonitoringOwnerGraph",
    "R5MonitoringPolicyProvider",
    "R5MonitoringPortfolioFactProvider",
    "R5MonitoringUnitOfWork",
    "R5PostPromotionMonitoringUnavailable",
]
