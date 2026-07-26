"""Pure policy-driven hedging rules."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from apps.policy.domain.entities import PolicyLevel


@dataclass(frozen=True)
class HedgeRule:
    """Configured hedge rule for one policy level."""

    ratio: Decimal
    instrument_code: str
    instrument_type: str
    estimated_cost_rate: Decimal

    def __post_init__(self) -> None:
        if not self.ratio.is_finite() or not Decimal("0") <= self.ratio <= Decimal("1"):
            raise ValueError("hedge ratio must be finite and in [0, 1]")
        if not self.estimated_cost_rate.is_finite() or self.estimated_cost_rate < 0:
            raise ValueError("hedge cost rate must be finite and non-negative")
        if self.ratio > 0 and not self.instrument_code.strip():
            raise ValueError("hedge instrument code is required")
        if self.ratio > 0 and not self.instrument_type.strip():
            raise ValueError("hedge instrument type is required")


@dataclass(frozen=True)
class HedgePolicyConfig:
    """Configured policy-level hedge rules from an external source."""

    rules: tuple[tuple[PolicyLevel, HedgeRule], ...]

    def rule_for(self, policy_level: PolicyLevel) -> HedgeRule:
        """Return the unique configured rule for a policy level."""

        matches = [rule for level, rule in self.rules if level is policy_level]
        if len(matches) != 1:
            raise ValueError(f"exactly one hedge rule is required for {policy_level.value}")
        return matches[0]


@dataclass(frozen=True)
class HedgeCalculationResult:
    """Validated policy hedge calculation."""

    should_hedge: bool
    policy_level: PolicyLevel
    hedge_ratio: float
    hedge_value: Decimal
    recommended_instrument: str
    instrument_type: str
    estimated_cost: Decimal
    reason: str

    def __post_init__(self) -> None:
        if self.policy_level is PolicyLevel.PENDING:
            raise ValueError("pending policy level cannot drive hedging")
        if not math.isfinite(self.hedge_ratio) or not 0.0 <= self.hedge_ratio <= 1.0:
            raise ValueError("hedge ratio must be finite and in [0, 1]")
        if not self.hedge_value.is_finite() or self.hedge_value < 0:
            raise ValueError("hedge value must be finite and non-negative")
        if not self.estimated_cost.is_finite() or self.estimated_cost < 0:
            raise ValueError("estimated cost must be finite and non-negative")
        if self.should_hedge != (self.hedge_ratio > 0):
            raise ValueError("should_hedge must match the hedge ratio")
        if self.should_hedge and (
            not self.recommended_instrument.strip() or not self.instrument_type.strip()
        ):
            raise ValueError("configured hedge instrument is required")


def calculate_policy_hedge(
    *,
    policy_level: PolicyLevel,
    portfolio_value: Decimal,
    equity_exposure: Decimal,
    config: HedgePolicyConfig,
) -> HedgeCalculationResult:
    """Calculate a hedge using externally configured rules."""

    if not portfolio_value.is_finite() or portfolio_value <= 0:
        raise ValueError("portfolio value must be finite and positive")
    if not equity_exposure.is_finite() or equity_exposure < 0 or equity_exposure > portfolio_value:
        raise ValueError("equity exposure must be finite and within portfolio value")

    rule = config.rule_for(policy_level)
    should_hedge = rule.ratio > 0
    hedge_value = equity_exposure * rule.ratio if should_hedge else Decimal("0")
    estimated_cost = hedge_value * rule.estimated_cost_rate
    reason = (
        f"政策档位 {policy_level.value} 触发对冲要求，对冲比例 {rule.ratio:.0%}"
        if should_hedge
        else f"政策档位 {policy_level.value} 无需对冲"
    )
    return HedgeCalculationResult(
        should_hedge=should_hedge,
        policy_level=policy_level,
        hedge_ratio=float(rule.ratio),
        hedge_value=hedge_value,
        recommended_instrument=rule.instrument_code if should_hedge else "",
        instrument_type=rule.instrument_type if should_hedge else "",
        estimated_cost=estimated_cost,
        reason=reason,
    )
