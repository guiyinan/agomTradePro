"""Fail-closed production composition for governed R8 optimization research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.portfolio.application.governed_optimization import (
    AppendGovernedOptimizationLifecycleEventUseCase,
    AssembleGovernedOptimizationProblemUseCase,
    ExactPortfolioLifecycleAuthorizationProvider,
    ExactPromotionProvider,
    GovernedOptimizationInputSetProvider,
    RunGovernedOptimizationResearchUseCase,
)
from apps.portfolio.domain.governed_input_set import (
    ExactPromotionAttestation,
    GovernedOptimizationInputSet,
)
from apps.portfolio.domain.optimization_lifecycle import (
    OptimizationLifecycleEventType,
    OptimizationLifecycleOwnerAttestation,
)
from apps.portfolio.infrastructure.deterministic_optimizer import (
    DeterministicConstrainedSearchAdapter,
)
from apps.portfolio.infrastructure.optimization_research_repository import (
    DjangoGovernedOptimizationResearchRepository,
)


class _UnavailableGovernedOptimizationInputSetProvider:
    """Deny R8 runs until Portfolio owns a persisted exact input-set query."""

    def get_exact(
        self,
        *,
        input_set_id: str,
        evaluated_at: datetime,
    ) -> GovernedOptimizationInputSet | None:
        """Never infer a canonical input set from result rows or caller payloads."""

        return None


class _UnavailableExactPromotionProvider:
    """Deny R8 promotion claims until Research exposes an exact owner port."""

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
    repository: DjangoGovernedOptimizationResearchRepository


def build_django_governed_optimization_research_runtime() -> (
    DjangoGovernedOptimizationResearchRuntime
):
    """Build the production runtime without fixture/default owner evidence."""

    repository = DjangoGovernedOptimizationResearchRepository()
    promotion_provider: ExactPromotionProvider = _UnavailableExactPromotionProvider()
    input_set_provider: GovernedOptimizationInputSetProvider = (
        _UnavailableGovernedOptimizationInputSetProvider()
    )
    lifecycle_authorization_provider: ExactPortfolioLifecycleAuthorizationProvider = (
        _UnavailablePortfolioLifecycleAuthorizationProvider()
    )
    assembler = AssembleGovernedOptimizationProblemUseCase(
        input_set_provider=input_set_provider,
        promotion_provider=promotion_provider,
    )
    return DjangoGovernedOptimizationResearchRuntime(
        run=RunGovernedOptimizationResearchUseCase(
            assembler=assembler,
            engine=DeterministicConstrainedSearchAdapter(),
            repository=repository,
        ),
        append_lifecycle=AppendGovernedOptimizationLifecycleEventUseCase(
            promotion_provider=promotion_provider,
            owner_authorization_provider=lifecycle_authorization_provider,
            repository=repository,
        ),
        repository=repository,
    )


__all__ = [
    "DjangoGovernedOptimizationResearchRuntime",
    "build_django_governed_optimization_research_runtime",
]
