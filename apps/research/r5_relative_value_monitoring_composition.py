"""Fail-closed production composition for R5 monitoring persistence."""

from __future__ import annotations

from dataclasses import dataclass

from apps.portfolio.infrastructure.r5_monitoring_raw_fact_repository import (
    DjangoPortfolioR5MonitoringRawFactRepository,
)
from apps.research.application.r5_monitoring_canonical_adapters import (
    R5FixedIncomeOwnerRecordQuery,
    R5MonitoringActiveLifecycleExactAdapter,
    R5MonitoringFixedIncomeExactAdapter,
)
from apps.research.application.r5_relative_value_monitoring import (
    EvaluateR5PostPromotionMonitoring,
    EvaluateR5PostPromotionMonitoringCommand,
    R5MonitoringClock,
)
from apps.research.application.r5_relative_value_monitoring_persistence import (
    AuditR5MonitoringAssessmentsCommand,
    GetExactR5MonitoringAssessment,
    R5MonitoringAuditPage,
    R5MonitoringPersistedAssessment,
    R5MonitoringPersistenceUnavailable,
    RegisterR5MonitoringAssessment,
)
from apps.research.application.r5_research_control_preflight import (
    EvaluateR5ResearchControlPreflight,
    R5ResearchControlActiveLifecycleProvider,
)
from apps.research.infrastructure.r5_monitoring_owner_repository import (
    DjangoR5MonitoringCalendarProvider,
    DjangoR5MonitoringOwnerRegistryRepository,
    DjangoR5MonitoringPolicyProvider,
)
from apps.research.infrastructure.r5_relative_value_monitoring_repository import (
    DjangoR5MonitoringClock,
    DjangoR5MonitoringRepository,
    _build_r5_monitoring_writer,
)
from apps.research.r5_research_control_composition import (
    _build_django_r5_research_control_test_runtime,
    build_django_r5_research_control_runtime,
)


class UnavailableR5MonitoringRegisterFacade:
    """Inert production writer until every canonical owner adapter exists."""

    __slots__ = ()

    def execute(
        self,
        command: EvaluateR5PostPromotionMonitoringCommand,
    ) -> R5MonitoringPersistedAssessment:
        """Reject registration without retaining a writer or owner object graph."""

        try:
            if type(command) is not EvaluateR5PostPromotionMonitoringCommand:
                raise TypeError
            EvaluateR5PostPromotionMonitoringCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring registration command is malformed"
            ) from error
        raise R5MonitoringPersistenceUnavailable(
            "canonical R5 monitoring owner providers are unavailable"
        )


class UnavailableR5MonitoringAuditFacade:
    """Inert audit writer; exact reads remain available separately."""

    __slots__ = ()

    def execute(self, command: AuditR5MonitoringAssessmentsCommand) -> R5MonitoringAuditPage:
        """Reject snapshot-producing audit until trusted internal composition exists."""

        try:
            if type(command) is not AuditR5MonitoringAssessmentsCommand:
                raise TypeError
            AuditR5MonitoringAssessmentsCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R5MonitoringPersistenceUnavailable(
                "R5 monitoring audit command is malformed"
            ) from error
        raise R5MonitoringPersistenceUnavailable(
            "canonical R5 monitoring audit composition is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoR5MonitoringRuntime:
    """Public runtime exposing no repository store, token, provider, or clock."""

    register: UnavailableR5MonitoringRegisterFacade
    get_exact: GetExactR5MonitoringAssessment
    audit: UnavailableR5MonitoringAuditFacade


@dataclass(frozen=True, slots=True)
class DjangoCanonicalR5MonitoringRuntime:
    """Public inert monitoring plus fail-closed research-control preflight."""

    register: UnavailableR5MonitoringRegisterFacade
    get_exact: GetExactR5MonitoringAssessment
    audit: UnavailableR5MonitoringAuditFacade
    preflight: EvaluateR5ResearchControlPreflight


@dataclass(frozen=True, slots=True)
class _DjangoCanonicalR5MonitoringTestRuntime:
    """Private canonical Phase-A/B and preflight success object graph."""

    register: RegisterR5MonitoringAssessment
    get_exact: GetExactR5MonitoringAssessment
    preflight: EvaluateR5ResearchControlPreflight


def build_django_r5_monitoring_runtime(
    *,
    using: str = "default",
) -> DjangoR5MonitoringRuntime:
    """Build safe exact reads and explicit unavailable mutation/audit facades."""

    repository = DjangoR5MonitoringRepository(using=using)
    return DjangoR5MonitoringRuntime(
        register=UnavailableR5MonitoringRegisterFacade(),
        get_exact=GetExactR5MonitoringAssessment(repository),
        audit=UnavailableR5MonitoringAuditFacade(),
    )


def build_django_canonical_r5_monitoring_runtime(
    *,
    using: str = "default",
) -> DjangoCanonicalR5MonitoringRuntime:
    """Expose no public write token and block until canonical ledgers are populated."""

    repository = DjangoR5MonitoringRepository(using=using)
    control = build_django_r5_research_control_runtime(using=using)
    return DjangoCanonicalR5MonitoringRuntime(
        register=UnavailableR5MonitoringRegisterFacade(),
        get_exact=GetExactR5MonitoringAssessment(repository),
        audit=UnavailableR5MonitoringAuditFacade(),
        preflight=control.preflight,
    )


def _build_django_canonical_r5_monitoring_test_runtime(
    *,
    active_lifecycle_provider: R5ResearchControlActiveLifecycleProvider,
    fixed_income_query: R5FixedIncomeOwnerRecordQuery,
    using: str = "default",
    clock: R5MonitoringClock | None = None,
) -> _DjangoCanonicalR5MonitoringTestRuntime:
    """Privately wire canonical owner reads into Phase A, Phase B, and preflight."""

    trusted_clock = clock or DjangoR5MonitoringClock()
    owner_repository = DjangoR5MonitoringOwnerRegistryRepository(using=using)
    fact_repository = DjangoPortfolioR5MonitoringRawFactRepository(using=using)
    evaluator = EvaluateR5PostPromotionMonitoring(
        policy_provider=DjangoR5MonitoringPolicyProvider(owner_repository),
        active_lifecycle_provider=R5MonitoringActiveLifecycleExactAdapter(
            active_lifecycle_provider
        ),
        calendar_provider=DjangoR5MonitoringCalendarProvider(owner_repository),
        fixed_income_provider=R5MonitoringFixedIncomeExactAdapter(fixed_income_query),
        portfolio_fact_provider=fact_repository,
        unit_of_work=owner_repository,
        clock=trusted_clock,
    )
    writer = _build_r5_monitoring_writer(using=using, clock=trusted_clock)
    read_repository = DjangoR5MonitoringRepository(using=using, clock=trusted_clock)
    control = _build_django_r5_research_control_test_runtime(
        active_lifecycle_provider=active_lifecycle_provider,
        fixed_income_query=fixed_income_query,
        using=using,
    )
    return _DjangoCanonicalR5MonitoringTestRuntime(
        register=RegisterR5MonitoringAssessment(evaluator=evaluator, writer=writer),
        get_exact=GetExactR5MonitoringAssessment(read_repository),
        preflight=control.preflight,
    )


__all__ = [
    "DjangoCanonicalR5MonitoringRuntime",
    "DjangoR5MonitoringRuntime",
    "UnavailableR5MonitoringAuditFacade",
    "UnavailableR5MonitoringRegisterFacade",
    "build_django_canonical_r5_monitoring_runtime",
    "build_django_r5_monitoring_runtime",
]
