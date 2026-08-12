"""Fail-closed production composition for R7 post-promotion monitoring."""

from __future__ import annotations

from dataclasses import dataclass

from apps.research.application.r7_post_promotion_monitoring import (
    EvaluateR7PostPromotionMonitoring,
    EvaluateR7PostPromotionMonitoringCommand,
    R7MonitoringActiveOwnerGraphProvider,
    R7MonitoringCalendarProvider,
    R7MonitoringClock,
    R7MonitoringPolicyProvider,
    R7MonitoringRealizationProvider,
)
from apps.research.application.r7_post_promotion_monitoring_persistence import (
    AuditR7MonitoringAssessments,
    AuditR7MonitoringAssessmentsCommand,
    GetExactR7MonitoringAssessment,
    R7MonitoringAuditPage,
    R7MonitoringPersistenceUnavailable,
    R7MonitoringReadRepository,
    R7PersistedMonitoringAssessment,
    RegisterR7MonitoringAssessment,
)
from apps.research.infrastructure.r7_post_promotion_monitoring_repository import (
    DjangoR7MonitoringClock,
    DjangoR7MonitoringRepository,
    _build_r7_monitoring_writer,
)


class UnavailableR7MonitoringRegisterFacade:
    """Stateless production write facade while canonical owners are absent."""

    __slots__ = ()

    def execute(
        self,
        command: EvaluateR7PostPromotionMonitoringCommand,
    ) -> R7PersistedMonitoringAssessment:
        """Validate shape, then fail closed without constructing a writer."""

        try:
            if type(command) is not EvaluateR7PostPromotionMonitoringCommand:
                raise TypeError
            command.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring registration command is malformed"
            ) from error
        raise R7MonitoringPersistenceUnavailable(
            "R7 monitoring canonical production owner providers are unavailable"
        )


class UnavailableR7MonitoringAuditFacade:
    """Stateless production audit facade while snapshot writer is unavailable."""

    __slots__ = ()

    def execute(
        self,
        command: AuditR7MonitoringAssessmentsCommand,
    ) -> R7MonitoringAuditPage:
        """Validate shape, then fail closed without a snapshot write capability."""

        try:
            if type(command) is not AuditR7MonitoringAssessmentsCommand:
                raise TypeError
            command.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise R7MonitoringPersistenceUnavailable(
                "R7 monitoring audit command is malformed"
            ) from error
        raise R7MonitoringPersistenceUnavailable(
            "R7 monitoring production audit persistence is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoR7MonitoringRuntime:
    """Public production capabilities with no writer, token, or owner adapters."""

    register: UnavailableR7MonitoringRegisterFacade
    get_exact: GetExactR7MonitoringAssessment
    audit: UnavailableR7MonitoringAuditFacade


def build_django_r7_monitoring_runtime(
    *,
    using: str = "default",
) -> DjangoR7MonitoringRuntime:
    """Build inert writes plus a read-only exact PIT query capability."""

    clock = DjangoR7MonitoringClock(using=using)
    repository = DjangoR7MonitoringRepository(using=using, clock=clock)
    return DjangoR7MonitoringRuntime(
        register=UnavailableR7MonitoringRegisterFacade(),
        get_exact=GetExactR7MonitoringAssessment(repository),
        audit=UnavailableR7MonitoringAuditFacade(),
    )


@dataclass(frozen=True, slots=True)
class _DjangoR7MonitoringTestRuntime:
    register: RegisterR7MonitoringAssessment
    get_exact: GetExactR7MonitoringAssessment
    audit: AuditR7MonitoringAssessments


def _build_django_r7_monitoring_test_runtime(
    *,
    policy_provider: R7MonitoringPolicyProvider,
    active_owner_graph_provider: R7MonitoringActiveOwnerGraphProvider,
    calendar_provider: R7MonitoringCalendarProvider,
    realization_provider: R7MonitoringRealizationProvider,
    clock: R7MonitoringClock,
    using: str = "default",
) -> _DjangoR7MonitoringTestRuntime:
    """Assemble injected test owners with the private claimed writer."""

    writer = _build_r7_monitoring_writer(using=using, clock=clock)
    evaluator = EvaluateR7PostPromotionMonitoring(
        policy_provider=policy_provider,
        active_owner_graph_provider=active_owner_graph_provider,
        calendar_provider=calendar_provider,
        realization_provider=realization_provider,
        clock=clock,
        unit_of_work=writer,
    )
    read_repository: R7MonitoringReadRepository = writer
    return _DjangoR7MonitoringTestRuntime(
        register=RegisterR7MonitoringAssessment(evaluator=evaluator, writer=writer),
        get_exact=GetExactR7MonitoringAssessment(read_repository),
        audit=AuditR7MonitoringAssessments(read_repository),
    )


__all__ = ["DjangoR7MonitoringRuntime", "build_django_r7_monitoring_runtime"]
