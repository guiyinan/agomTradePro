"""Fail-closed production composition for governed R8 optimization research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.portfolio.application.governed_optimization import (
    AppendGovernedOptimizationLifecycleEventUseCase,
    AssembleGovernedOptimizationProblemUseCase,
    ExactPortfolioLifecycleAuthorizationProvider,
    ExactPromotionProvider,
    RunGovernedOptimizationResearchUseCase,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationLifecycleEventType,
    OptimizationLifecycleOwnerAttestation,
)
from apps.portfolio.infrastructure.deterministic_optimizer import (
    DeterministicConstrainedSearchAdapter,
)
from apps.portfolio.infrastructure.optimization_input_receipt_repository import (
    DjangoGovernedOptimizationInputReceiptRepository,
    DjangoGovernedOptimizationUnitOfWork,
)
from apps.portfolio.infrastructure.optimization_research_repository import (
    DjangoGovernedOptimizationResearchRepository,
)


class _UnavailableExactPromotionProvider:
    """Deny R8 promotion claims until Research exposes an exact owner port."""

    def __init__(self, *, unit_of_work_key: str) -> None:
        self._unit_of_work_key = unit_of_work_key

    @property
    def unit_of_work_key(self) -> str:
        """Share the exact run UoW without exposing any evidence source."""

        return self._unit_of_work_key

    def get_exact(
        self,
        *,
        capability_key: str,
        decision_id: str,
        evaluated_at: datetime,
    ) -> ExactPromotionAttestation | None:
        """Never accept caller-supplied R3/R4/R5/R8 promotion evidence."""

        return None


class _UnavailablePortfolioLifecycleAuthorizationProvider:
    """Deny terminal lifecycle events until Portfolio owns an exact authorization port."""

    def get_exact(
        self,
        *,
        attestation_id: str,
        result_id: str,
        result_hash: str,
        event_type: OptimizationLifecycleEventType,
        evaluated_at: datetime,
    ) -> OptimizationLifecycleOwnerAttestation | None:
        """Never synthesize retirement or rollback authorization."""

        return None


@dataclass(frozen=True)
class DjangoGovernedOptimizationResearchRuntime:
    """Constructable R8 runtime whose missing owner sources fail before writes."""

    run: RunGovernedOptimizationResearchUseCase
    append_lifecycle: AppendGovernedOptimizationLifecycleEventUseCase


def build_django_governed_optimization_research_runtime() -> (
    DjangoGovernedOptimizationResearchRuntime
):
    """Build the production runtime without fixture/default owner evidence."""

    unit_of_work = DjangoGovernedOptimizationUnitOfWork()
    input_receipt_provider = DjangoGovernedOptimizationInputReceiptRepository(
        unit_of_work=unit_of_work
    )
    repository = DjangoGovernedOptimizationResearchRepository(
        unit_of_work=unit_of_work,
        receipt_provider=input_receipt_provider,
    )
    promotion_provider: ExactPromotionProvider = _UnavailableExactPromotionProvider(
        unit_of_work_key=unit_of_work.unit_of_work_key
    )
    lifecycle_authorization_provider: ExactPortfolioLifecycleAuthorizationProvider = (
        _UnavailablePortfolioLifecycleAuthorizationProvider()
    )
    assembler = AssembleGovernedOptimizationProblemUseCase(
        input_set_provider=input_receipt_provider,
        promotion_provider=promotion_provider,
    )
    return DjangoGovernedOptimizationResearchRuntime(
        run=RunGovernedOptimizationResearchUseCase(
            assembler=assembler,
            engine=DeterministicConstrainedSearchAdapter(),
            repository=repository,
            input_receipt_provider=input_receipt_provider,
            promotion_provider=promotion_provider,
        ),
        append_lifecycle=AppendGovernedOptimizationLifecycleEventUseCase(
            promotion_provider=promotion_provider,
            owner_authorization_provider=lifecycle_authorization_provider,
            repository=repository,
        ),
    )


__all__ = [
    "DjangoGovernedOptimizationResearchRuntime",
    "build_django_governed_optimization_research_runtime",
]
