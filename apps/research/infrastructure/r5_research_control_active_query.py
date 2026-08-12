"""Canonical read-only Research 0006 lifecycle query for R5 preflight."""

from __future__ import annotations

from datetime import datetime

from apps.fixed_income.domain.evidence import require_aware, require_sha256
from apps.fixed_income.infrastructure.relative_value_repository import (
    DjangoR5RelativeValueRepository,
)
from apps.portfolio.domain.r5_relative_value_outcome import R5PortfolioOutcomeSeal
from apps.research.application.r5_relative_value_promotion_decision import (
    R5RelativeValuePromotionRef,
)
from apps.research.application.r5_relative_value_promotion_lifecycle import (
    GetActiveR5RelativeValuePromotion,
)
from apps.research.application.r5_research_control_adapters import (
    R5ActiveLifecycleExactAdapter,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
)
from apps.research.infrastructure.r5_relative_value_promotion_repository import (
    DjangoR5DecisionAuthorizationProvider,
    DjangoR5PromotionPolicyProvider,
    DjangoR5PromotionRepository,
    DjangoR5PromotionTrialProvider,
)


class _UnavailableCanonicalPortfolioOutcomeProvider:
    """Fail closed until Portfolio can reconstruct its upstream source owner."""

    __slots__ = ("_unit_of_work_key",)

    def __init__(self, *, unit_of_work_key: str) -> None:
        if type(unit_of_work_key) is not str or not unit_of_work_key:
            raise ValueError("R5 Portfolio outcome unit of work is invalid")
        self._unit_of_work_key = unit_of_work_key

    @property
    def unit_of_work_key(self) -> str:
        """Return the enclosing canonical database transaction identity."""

        return self._unit_of_work_key

    def get_exact(
        self,
        *,
        outcome_ref: R5RelativeValuePromotionRef,
        expected_owner_record_hash: str,
        as_of: datetime,
    ) -> R5PortfolioOutcomeSeal | None:
        """Validate the exact request, then report missing source-owned evidence."""

        if type(outcome_ref) is not R5RelativeValuePromotionRef:
            raise TypeError("R5 Portfolio outcome reference type differs")
        R5RelativeValuePromotionRef.__post_init__(outcome_ref)
        require_sha256(expected_owner_record_hash, "expected_owner_record_hash")
        require_aware(as_of, "as_of")
        return None


class DjangoR5ResearchControlActiveLifecycleProvider:
    """Replay Research 0006 through every constructible canonical exact owner."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        if type(using) is not str or not using or using != using.strip():
            raise ValueError("R5 research-control database alias is invalid")
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the canonical database transaction identity."""

        return f"django:{self._using}"

    def get_active(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R5MonitoringActiveLifecycle | None:
        """Select the active PIT lifecycle without retaining mutation authority."""

        repository = DjangoR5PromotionRepository(using=self._using)
        active_query = GetActiveR5RelativeValuePromotion(
            policy_provider=DjangoR5PromotionPolicyProvider(repository),
            trial_provider=DjangoR5PromotionTrialProvider(repository),
            owner_record_provider=DjangoR5RelativeValueRepository(using=self._using),
            portfolio_outcome_provider=_UnavailableCanonicalPortfolioOutcomeProvider(
                unit_of_work_key=repository.unit_of_work_key
            ),
            decision_authorization_provider=DjangoR5DecisionAuthorizationProvider(repository),
            repository=repository,
        )
        return R5ActiveLifecycleExactAdapter(
            active_query=active_query,
            lifecycle_stream=repository,
        ).get_active(scope_id=scope_id, as_of=as_of)


__all__ = ["DjangoR5ResearchControlActiveLifecycleProvider"]
