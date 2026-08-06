"""Composition root for persisted Research R4 promotion workflows."""

from __future__ import annotations

from dataclasses import dataclass

from apps.portfolio.application.macro_risk_rolling_research import (
    ExactR3PromotionProvider,
)
from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchExactQuery,
)
from apps.research.application.r4_promotion_decision import EvaluateR4PromotionUseCase
from apps.research.application.r4_promotion_lifecycle import (
    AppendR4PromotionLifecycleEventUseCase,
    R4ActivePromotionProvider,
)
from apps.research.application.r4_promotion_registration import R4PromotionClock
from apps.research.infrastructure.r4_promotion_providers import (
    DjangoR4DecisionReceiptProvider,
    DjangoR4LifecycleAuthorizationProvider,
    DjangoR4PromotionPolicyProvider,
    R4LifecycleAuthorizationSource,
)
from apps.research.infrastructure.r4_promotion_repository import (
    DjangoR4PromotionRepository,
)


@dataclass(frozen=True)
class DjangoR4PromotionRuntime:
    """Fully wired Research-only R4 persistence runtime."""

    repository: DjangoR4PromotionRepository
    policy_provider: DjangoR4PromotionPolicyProvider
    decision_receipt_provider: DjangoR4DecisionReceiptProvider
    lifecycle_authorization_provider: DjangoR4LifecycleAuthorizationProvider
    evaluate: EvaluateR4PromotionUseCase
    append_lifecycle: AppendR4PromotionLifecycleEventUseCase
    active: R4ActivePromotionProvider


def build_django_r4_promotion_runtime(
    *,
    portfolio_query: R4RollingResearchExactQuery,
    current_r3_provider: ExactR3PromotionProvider,
    lifecycle_authorization_source: R4LifecycleAuthorizationSource,
    clock: R4PromotionClock | None = None,
    using: str = "default",
) -> DjangoR4PromotionRuntime:
    """Wire Research persistence to injected Portfolio Application ports."""

    repository = DjangoR4PromotionRepository(
        portfolio_query=portfolio_query,
        current_r3_provider=current_r3_provider,
        clock=clock,
        using=using,
    )
    policy_provider = DjangoR4PromotionPolicyProvider(repository)
    receipt_provider = DjangoR4DecisionReceiptProvider(repository)
    authorization_provider = DjangoR4LifecycleAuthorizationProvider(
        repository,
        owner_source=lifecycle_authorization_source,
    )
    return DjangoR4PromotionRuntime(
        repository=repository,
        policy_provider=policy_provider,
        decision_receipt_provider=receipt_provider,
        lifecycle_authorization_provider=authorization_provider,
        evaluate=EvaluateR4PromotionUseCase(
            policy_provider=policy_provider,
            portfolio_query=portfolio_query,
            current_r3_provider=current_r3_provider,
            receipt_provider=receipt_provider,
            repository=repository,
        ),
        append_lifecycle=AppendR4PromotionLifecycleEventUseCase(
            policy_provider=policy_provider,
            portfolio_query=portfolio_query,
            current_r3_provider=current_r3_provider,
            authorization_provider=authorization_provider,
            repository=repository,
        ),
        active=R4ActivePromotionProvider(
            policy_provider=policy_provider,
            portfolio_query=portfolio_query,
            current_r3_provider=current_r3_provider,
            repository=repository,
        ),
    )


__all__ = ["DjangoR4PromotionRuntime", "build_django_r4_promotion_runtime"]
