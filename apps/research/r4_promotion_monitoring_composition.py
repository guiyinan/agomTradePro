"""Fail-closed production composition for R4 monitoring persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.portfolio.application.macro_risk_rolling_research import (
    ExactR3PromotionProvider,
)
from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchExactQuery,
)
from apps.portfolio.infrastructure.r4_monitoring_raw_fact_repository import (
    DjangoPortfolioR4MonitoringRawFactRepository,
)
from apps.research.application.r4_promotion_lifecycle import R4ActivePromotionProvider
from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoring,
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringClock,
)
from apps.research.application.r4_promotion_monitoring_persistence import (
    AuditR4MonitoringAssessmentsCommand,
    GetExactR4MonitoringAssessment,
    R4MonitoringPersistenceUnavailable,
    RegisterR4MonitoringAssessment,
)
from apps.research.infrastructure.r4_promotion_monitoring_owner_adapters import (
    R4MonitoringActiveDecisionAdapter,
    R4MonitoringPortfolioResultAdapter,
    R4MonitoringR3AttestationAdapter,
    R4MonitoringRawFactAdapter,
)
from apps.research.infrastructure.r4_promotion_monitoring_owner_repository import (
    DjangoR4MonitoringCalendarProvider,
    DjangoR4MonitoringOwnerRegistryRepository,
    DjangoR4MonitoringPolicyProvider,
)
from apps.research.infrastructure.r4_promotion_monitoring_repository import (
    DjangoR4MonitoringClock,
    DjangoR4MonitoringRepository,
    _DjangoR4MonitoringStore,
)


class UnavailableR4MonitoringRegisterFacade:
    """Expose no write capability until every canonical owner is wired."""

    __slots__ = ()

    def execute(self, command: EvaluateR4PromotionMonitoringCommand) -> NoReturn:
        """Revalidate the ID-only command and fail before persistence access."""

        try:
            if type(command) is not EvaluateR4PromotionMonitoringCommand:
                raise TypeError("R4 monitoring command type differs")
            EvaluateR4PromotionMonitoringCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring registration command is malformed"
            ) from error
        raise R4MonitoringPersistenceUnavailable(
            "canonical R4 monitoring owner providers are unavailable"
        )


class UnavailableR4MonitoringAuditFacade:
    """Keep audit snapshot writes outside the public runtime object graph."""

    __slots__ = ()

    def execute(self, command: AuditR4MonitoringAssessmentsCommand) -> NoReturn:
        """Validate the query and fail until an internal snapshot writer is wired."""

        try:
            if type(command) is not AuditR4MonitoringAssessmentsCommand:
                raise TypeError("R4 monitoring audit command type differs")
            AuditR4MonitoringAssessmentsCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R4MonitoringPersistenceUnavailable(
                "R4 monitoring audit query is malformed"
            ) from error
        raise R4MonitoringPersistenceUnavailable(
            "R4 monitoring audit snapshot writer is unavailable in production composition"
        )


@dataclass(frozen=True)
class DjangoR4MonitoringRuntime:
    """Read-safe runtime with inert registration and audit surfaces."""

    register: UnavailableR4MonitoringRegisterFacade
    get_exact: GetExactR4MonitoringAssessment
    audit: UnavailableR4MonitoringAuditFacade


@dataclass(frozen=True)
class DjangoCanonicalR4MonitoringRuntime:
    """Public canonical reads with an inert assessment registration surface."""

    register: UnavailableR4MonitoringRegisterFacade
    get_exact: GetExactR4MonitoringAssessment
    audit: UnavailableR4MonitoringAuditFacade


@dataclass(frozen=True)
class _DjangoCanonicalR4MonitoringTestRuntime:
    """Private injected runtime proving the canonical six-owner adapter graph."""

    register: RegisterR4MonitoringAssessment
    get_exact: GetExactR4MonitoringAssessment


def build_django_r4_monitoring_runtime(
    *,
    using: str = "default",
    clock: R4MonitoringClock | None = None,
) -> DjangoR4MonitoringRuntime:
    """Build production reads without retaining any store or write token."""

    repository = DjangoR4MonitoringRepository(
        using=using,
        clock=clock or DjangoR4MonitoringClock(),
    )
    return DjangoR4MonitoringRuntime(
        register=UnavailableR4MonitoringRegisterFacade(),
        get_exact=GetExactR4MonitoringAssessment(repository),
        audit=UnavailableR4MonitoringAuditFacade(),
    )


def build_django_canonical_r4_monitoring_runtime(
    *, using: str = "default"
) -> DjangoCanonicalR4MonitoringRuntime:
    """Expose exact reads; canonical source owners are not yet constructible here."""

    repository = DjangoR4MonitoringRepository(
        using=using,
        clock=DjangoR4MonitoringClock(),
    )
    return DjangoCanonicalR4MonitoringRuntime(
        register=UnavailableR4MonitoringRegisterFacade(),
        get_exact=GetExactR4MonitoringAssessment(repository),
        audit=UnavailableR4MonitoringAuditFacade(),
    )


def _build_django_canonical_r4_monitoring_test_runtime(
    *,
    active_promotion_provider: R4ActivePromotionProvider,
    portfolio_query: R4RollingResearchExactQuery,
    current_r3_provider: ExactR3PromotionProvider,
    using: str = "default",
    clock: R4MonitoringClock | None = None,
) -> _DjangoCanonicalR4MonitoringTestRuntime:
    """Privately prove the canonical adapters without exporting write authority."""

    trusted_clock = clock or DjangoR4MonitoringClock()
    uow_key = f"django:{using}"
    owner_repository = DjangoR4MonitoringOwnerRegistryRepository(using=using)
    raw_repository = DjangoPortfolioR4MonitoringRawFactRepository(using=using)
    evaluator = EvaluateR4PromotionMonitoring(
        active_decision_provider=R4MonitoringActiveDecisionAdapter(
            active_promotion_provider,
            unit_of_work_key=uow_key,
        ),
        policy_provider=DjangoR4MonitoringPolicyProvider(owner_repository),
        portfolio_result_provider=R4MonitoringPortfolioResultAdapter(portfolio_query),
        r3_attestation_provider=R4MonitoringR3AttestationAdapter(
            current_r3_provider,
            unit_of_work_key=uow_key,
        ),
        period_calendar_provider=DjangoR4MonitoringCalendarProvider(owner_repository),
        raw_fact_provider=R4MonitoringRawFactAdapter(raw_repository),
        unit_of_work=owner_repository,
        clock=trusted_clock,
    )
    writer = _DjangoR4MonitoringStore(using=using, clock=trusted_clock)
    read_repository = DjangoR4MonitoringRepository(using=using, clock=trusted_clock)
    return _DjangoCanonicalR4MonitoringTestRuntime(
        register=RegisterR4MonitoringAssessment(evaluator=evaluator, writer=writer),
        get_exact=GetExactR4MonitoringAssessment(read_repository),
    )


__all__ = [
    "DjangoCanonicalR4MonitoringRuntime",
    "DjangoR4MonitoringRuntime",
    "UnavailableR4MonitoringAuditFacade",
    "UnavailableR4MonitoringRegisterFacade",
    "build_django_canonical_r4_monitoring_runtime",
    "build_django_r4_monitoring_runtime",
]
