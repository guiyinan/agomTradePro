"""Owner registration input for server-clocked R4 promotion policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind
from apps.research.domain.r4_promotion_scope_policy import (
    R4PromotionPolicy,
    R4PromotionScope,
    R4PromotionStudyRegistration,
)


class R4PromotionClock(Protocol):
    """Injectable authoritative clock used only by the Research repository."""

    def now(self) -> datetime:
        """Return one timezone-aware authoritative receipt time."""


@dataclass(frozen=True)
class R4PromotionPolicyRegistrationDraft:
    """Pre-registration input excluding server receipt and derived content hash."""

    policy_id: str
    policy_version: str
    scope: R4PromotionScope
    registration: R4PromotionStudyRegistration
    required_methods: tuple[MacroRiskCandidateKind, ...]
    reference_methods: tuple[MacroRiskCandidateKind, ...]
    minimum_fold_count: int
    minimum_regime_coverage_ratio: Decimal
    minimum_relative_net_return: Decimal
    maximum_relative_drawdown_increase: Decimal
    maximum_relative_volatility_increase: Decimal
    maximum_relative_cost_increase: Decimal
    decision_validity_seconds: int
    approved_at: datetime
    active_from: datetime
    active_until: datetime

    @classmethod
    def from_policy(
        cls,
        policy: R4PromotionPolicy,
    ) -> R4PromotionPolicyRegistrationDraft:
        """Discard caller-owned receipt/hash fields from an existing policy value."""

        return cls(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            scope=policy.scope,
            registration=policy.registration,
            required_methods=policy.required_methods,
            reference_methods=policy.reference_methods,
            minimum_fold_count=policy.minimum_fold_count,
            minimum_regime_coverage_ratio=policy.minimum_regime_coverage_ratio,
            minimum_relative_net_return=policy.minimum_relative_net_return,
            maximum_relative_drawdown_increase=policy.maximum_relative_drawdown_increase,
            maximum_relative_volatility_increase=policy.maximum_relative_volatility_increase,
            maximum_relative_cost_increase=policy.maximum_relative_cost_increase,
            decision_validity_seconds=policy.decision_validity_seconds,
            approved_at=policy.approved_at,
            active_from=policy.active_from,
            active_until=policy.active_until,
        )

    def materialize(self, *, recorded_at: datetime) -> R4PromotionPolicy:
        """Create the canonical policy using only the repository receipt clock."""

        return R4PromotionPolicy.create(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            scope=self.scope,
            registration=self.registration,
            required_methods=self.required_methods,
            reference_methods=self.reference_methods,
            minimum_fold_count=self.minimum_fold_count,
            minimum_regime_coverage_ratio=self.minimum_regime_coverage_ratio,
            minimum_relative_net_return=self.minimum_relative_net_return,
            maximum_relative_drawdown_increase=self.maximum_relative_drawdown_increase,
            maximum_relative_volatility_increase=self.maximum_relative_volatility_increase,
            maximum_relative_cost_increase=self.maximum_relative_cost_increase,
            decision_validity_seconds=self.decision_validity_seconds,
            approved_at=self.approved_at,
            recorded_at=recorded_at,
            active_from=self.active_from,
            active_until=self.active_until,
        )


__all__ = ["R4PromotionClock", "R4PromotionPolicyRegistrationDraft"]
