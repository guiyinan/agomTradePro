"""Private fail-closed R8 Phase A/B owner composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.portfolio.application.governed_optimization_monitoring import (
    EvaluateGovernedOptimizationMonitoring,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.governed_optimization_monitoring import (
    OptimizationPromotionSelector,
)
from apps.portfolio.governed_optimization_monitoring_composition import (
    UnavailableGovernedOptimizationMonitoringRegisterFacade,
)
from apps.portfolio.infrastructure.governed_optimization_monitoring_repository import (
    DjangoGovernedOptimizationMonitoringClock,
)
from apps.portfolio.infrastructure.r8_broker_monitoring_feedback_adapter import (
    DjangoR8BrokerMonitoringFeedbackAdapter,
)
from apps.portfolio.infrastructure.r8_monitoring_calendar_repository import (
    DjangoR8MonitoringCalendarRegistryRepository,
)
from apps.portfolio.infrastructure.r8_monitoring_owner_adapters import (
    DjangoR8MonitoringActiveResultProvider,
    DjangoR8MonitoringInputReceiptProvider,
    DjangoR8MonitoringReadUnitOfWork,
)
from apps.portfolio.infrastructure.r8_portfolio_monitoring_feedback_adapter import (
    DjangoPortfolioR8MonitoringFeedbackAdapter,
    DjangoR8MonitoringRawFactAdapter,
)
from apps.research.infrastructure.r8_monitoring_policy_repository import (
    DjangoR8MonitoringPolicyRepository,
)


class _UnavailableR8PromotionProvider:
    """Explicit absence until canonical R3/R4/R5 Promotion providers exist."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str) -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        selector: OptimizationPromotionSelector,
        as_of: datetime,
    ) -> ExactPromotionAttestation | None:
        """Preserve unavailable Promotions as explicit absence."""

        if type(selector) is not OptimizationPromotionSelector:
            raise TypeError("R8 Promotion selector must use the exact Domain type")
        OptimizationPromotionSelector.__post_init__(selector)
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("R8 Promotion cutoff must be timezone-aware")
        return None


@dataclass(frozen=True, slots=True)
class _DjangoR8PhaseABRuntime:
    """Complete Phase A read graph with a deliberately inert Phase B surface."""

    evaluate: EvaluateGovernedOptimizationMonitoring
    register: UnavailableGovernedOptimizationMonitoringRegisterFacade


def _build_django_r8_phase_a_b_runtime(*, using: str = "default") -> _DjangoR8PhaseABRuntime:
    """Compose exact owners while absent Promotions force BLOCKED and zero-write."""

    promotion = _UnavailableR8PromotionProvider(using=using)
    evaluator = EvaluateGovernedOptimizationMonitoring(
        active_result_provider=DjangoR8MonitoringActiveResultProvider(using=using),
        receipt_provider=DjangoR8MonitoringInputReceiptProvider(using=using),
        r3_promotion_provider=promotion,
        r4_promotion_provider=promotion,
        r5_promotion_provider=promotion,
        policy_provider=DjangoR8MonitoringPolicyRepository(using=using),
        calendar_provider=DjangoR8MonitoringCalendarRegistryRepository(using=using),
        portfolio_feedback_provider=DjangoPortfolioR8MonitoringFeedbackAdapter(using=using),
        broker_feedback_provider=DjangoR8BrokerMonitoringFeedbackAdapter(using=using),
        raw_fact_provider=DjangoR8MonitoringRawFactAdapter(using=using),
        unit_of_work=DjangoR8MonitoringReadUnitOfWork(using=using),
        clock=DjangoGovernedOptimizationMonitoringClock(),
    )
    return _DjangoR8PhaseABRuntime(
        evaluate=evaluator,
        register=UnavailableGovernedOptimizationMonitoringRegisterFacade(),
    )


__all__: tuple[str, ...] = ()
