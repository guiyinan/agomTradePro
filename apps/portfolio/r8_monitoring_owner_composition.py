"""Capability-isolated Portfolio owner composition for R8 monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from apps.portfolio.application.governed_optimization_monitoring import (
    EvaluateGovernedOptimizationMonitoring,
)
from apps.portfolio.application.r8_monitoring_calendar_registry import (
    R8MonitoringCalendarDefinitionProvider,
    R8MonitoringCalendarRegistryClock,
    R8MonitoringCalendarRegistryUnavailable,
    R8MonitoringCalendarSourceProvider,
    RegisterR8MonitoringCalendar,
    RegisterR8MonitoringCalendarCommand,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.governed_optimization_monitoring import (
    GovernedOptimizationMonitoringPolicy,
    OptimizationMonitoringPeriodObservation,
    OptimizationMonitoringSourceEvidence,
    OptimizationPromotionSelector,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_repository import (
    DjangoGovernedOptimizationMonitoringClock,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.r8_broker_monitoring_feedback_adapter import (
    DjangoR8BrokerMonitoringFeedbackAdapter,
)
from apps.portfolio.infrastructure.r8_monitoring_calendar_repository import (
    DjangoR8MonitoringCalendarRegistryClock,
    DjangoR8MonitoringCalendarRegistryRepository,
    _build_r8_monitoring_calendar_store,
)
from apps.portfolio.infrastructure.r8_monitoring_owner_adapters import (
    DjangoR8MonitoringActiveResultProvider,
    DjangoR8MonitoringInputReceiptProvider,
    DjangoR8MonitoringReadUnitOfWork,
)


class UnavailableR8MonitoringCalendarRegistrationFacade:
    """Stateless public mutation facade while canonical sources are unwired."""

    __slots__ = ()

    def execute(self, command: RegisterR8MonitoringCalendarCommand) -> NoReturn:
        """Class-bound validate identity input, then fail before database access."""

        try:
            if type(command) is not RegisterR8MonitoringCalendarCommand:
                raise TypeError("calendar registration command type differs")
            RegisterR8MonitoringCalendarCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R8MonitoringCalendarRegistryUnavailable(
                "malformed R8 monitoring calendar registration command"
            ) from error
        raise R8MonitoringCalendarRegistryUnavailable(
            "canonical R8 monitoring calendar definition/source is unavailable"
        )


class _UnavailableR8MonitoringPolicyProvider:
    __slots__ = ("_using",)

    def __init__(self, *, using: str) -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        as_of: datetime,
    ) -> GovernedOptimizationMonitoringPolicy | None:
        del policy_id, policy_version, expected_policy_hash, as_of
        return None


class _UnavailableR8MonitoringPromotionProvider:
    __slots__ = ("_using",)

    def __init__(self, *, using: str) -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        selector: OptimizationPromotionSelector,
        as_of: datetime,
    ) -> ExactPromotionAttestation | None:
        del selector, as_of
        return None


class _UnavailableR8MonitoringFeedbackProvider:
    __slots__ = ("_using",)

    def __init__(self, *, using: str) -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

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
        del (
            result_id,
            result_hash,
            receipt_id,
            receipt_hash,
            calendar_id,
            calendar_hash,
            period_ids,
            as_of,
        )
        return ()


class _UnavailableR8MonitoringRawFactProvider:
    __slots__ = ("_using",)

    def __init__(self, *, using: str) -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

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
        del (
            result_id,
            result_hash,
            receipt_id,
            receipt_hash,
            policy_id,
            policy_hash,
            calendar_id,
            calendar_hash,
            period_ids,
            as_of,
        )
        return ()


@dataclass(frozen=True)
class DjangoR8MonitoringOwnerRuntime:
    """Read-only owner adapters/evaluator plus inert calendar registration."""

    register_calendar: UnavailableR8MonitoringCalendarRegistrationFacade
    active_result_provider: DjangoR8MonitoringActiveResultProvider
    receipt_provider: DjangoR8MonitoringInputReceiptProvider
    calendar_provider: DjangoR8MonitoringCalendarRegistryRepository
    evaluate: EvaluateGovernedOptimizationMonitoring


@dataclass(frozen=True)
class _DjangoR8MonitoringCalendarRegistrationRuntime:
    """Private source-injected calendar registration runtime for owner tests."""

    register_calendar: RegisterR8MonitoringCalendar
    calendar_provider: DjangoR8MonitoringCalendarRegistryRepository


def build_django_r8_monitoring_owner_runtime(
    *, using: str = "default"
) -> DjangoR8MonitoringOwnerRuntime:
    """Build Portfolio exact reads while absent external owners remain blocked."""

    active = DjangoR8MonitoringActiveResultProvider(using=using)
    receipt = DjangoR8MonitoringInputReceiptProvider(using=using)
    calendar = DjangoR8MonitoringCalendarRegistryRepository(using=using)
    policy = _UnavailableR8MonitoringPolicyProvider(using=using)
    promotion = _UnavailableR8MonitoringPromotionProvider(using=using)
    portfolio_feedback = _UnavailableR8MonitoringFeedbackProvider(using=using)
    broker_feedback = DjangoR8BrokerMonitoringFeedbackAdapter(using=using)
    raw_fact = _UnavailableR8MonitoringRawFactProvider(using=using)
    evaluator = EvaluateGovernedOptimizationMonitoring(
        active_result_provider=active,
        receipt_provider=receipt,
        r3_promotion_provider=promotion,
        r4_promotion_provider=promotion,
        r5_promotion_provider=promotion,
        policy_provider=policy,
        calendar_provider=calendar,
        portfolio_feedback_provider=portfolio_feedback,
        broker_feedback_provider=broker_feedback,
        raw_fact_provider=raw_fact,
        unit_of_work=DjangoR8MonitoringReadUnitOfWork(using=using),
        clock=DjangoGovernedOptimizationMonitoringClock(),
    )
    return DjangoR8MonitoringOwnerRuntime(
        register_calendar=UnavailableR8MonitoringCalendarRegistrationFacade(),
        active_result_provider=active,
        receipt_provider=receipt,
        calendar_provider=calendar,
        evaluate=evaluator,
    )


def _build_django_r8_monitoring_calendar_registration_runtime(
    *,
    definition_provider: R8MonitoringCalendarDefinitionProvider,
    source_provider: R8MonitoringCalendarSourceProvider,
    clock: R8MonitoringCalendarRegistryClock | None = None,
    using: str = "default",
    unit_of_work: DjangoGovernedOptimizationUnitOfWork | None = None,
) -> _DjangoR8MonitoringCalendarRegistrationRuntime:
    """Wire private source-backed registration without exporting its store."""

    owner_uow = unit_of_work or DjangoGovernedOptimizationUnitOfWork(using=using)
    trusted_clock = clock or DjangoR8MonitoringCalendarRegistryClock(
        using=using,
        unit_of_work=owner_uow,
    )
    return _DjangoR8MonitoringCalendarRegistrationRuntime(
        register_calendar=RegisterR8MonitoringCalendar(
            definition_provider=definition_provider,
            source_provider=source_provider,
            store=_build_r8_monitoring_calendar_store(
                using=using,
                unit_of_work=owner_uow,
            ),
            clock=trusted_clock,
        ),
        calendar_provider=DjangoR8MonitoringCalendarRegistryRepository(using=using),
    )


__all__ = [
    "DjangoR8MonitoringOwnerRuntime",
    "UnavailableR8MonitoringCalendarRegistrationFacade",
    "build_django_r8_monitoring_owner_runtime",
]
