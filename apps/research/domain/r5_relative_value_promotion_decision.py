"""Derived Research decision for one exact R5 relative-value trial."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import TypedDict

from apps.fixed_income.domain.evidence import (
    canonical_hash as _strict_canonical_hash,
)
from apps.fixed_income.domain.evidence import (
    require_aware,
    require_sha256,
    require_token,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
    R5RelativeValuePromotionScope,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
    R5RelativeValuePromotionTrialState,
)


def _canonical_hash(payload: object) -> str:
    """Hash after narrowing payload list syntax to exact tuples."""

    return _strict_canonical_hash(_tuple_payload(payload))


def _tuple_payload(value: object) -> object:
    if isinstance(value, list):
        return tuple(_tuple_payload(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_tuple_payload(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _tuple_payload(item) for key, item in value.items()}
    return value


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


class R5RelativeValuePromotionDecisionOutcome(str, Enum):
    """Automatically derived R5 promotion outcome."""

    APPROVED = "approved"
    REJECTED = "rejected"


class R5RelativeValuePromotionGateCode(str, Enum):
    """Stable gates applied to exact R5 trial evidence."""

    TRIAL_READY = "trial_ready"
    MINIMUM_OBSERVATIONS = "minimum_observations"
    MINIMUM_COVERAGE = "minimum_coverage"
    MINIMUM_EXCESS_NET_RETURN = "minimum_excess_net_return"
    MAXIMUM_DRAWDOWN_INCREASE = "maximum_drawdown_increase"
    MAXIMUM_TOTAL_COST = "maximum_total_cost"
    MAXIMUM_LIQUIDITY_BREACH_RATIO = "maximum_liquidity_breach_ratio"
    MAXIMUM_CAPACITY_UTILIZATION = "maximum_capacity_utilization"
    MAXIMUM_REALIZED_CREDIT_LOSS = "maximum_realized_credit_loss"


class _PerformanceValues(TypedDict):
    observation_count: int
    target_compounded_net_return: Decimal
    benchmark_compounded_net_return: Decimal
    excess_net_return: Decimal
    target_maximum_drawdown: Decimal
    benchmark_maximum_drawdown: Decimal
    drawdown_increase: Decimal
    total_cost: Decimal
    liquidity_breach_ratio: Decimal
    peak_capacity_utilization: Decimal
    total_realized_credit_loss: Decimal
    observation_hashes: tuple[str, ...]


@dataclass(frozen=True)
class R5RelativeValueTrialPerformance:
    """Server-derived aggregate metrics over all exact trial observations."""

    observation_count: int
    target_compounded_net_return: Decimal
    benchmark_compounded_net_return: Decimal
    excess_net_return: Decimal
    target_maximum_drawdown: Decimal
    benchmark_maximum_drawdown: Decimal
    drawdown_increase: Decimal
    total_cost: Decimal
    liquidity_breach_ratio: Decimal
    peak_capacity_utilization: Decimal
    total_realized_credit_loss: Decimal
    observation_hashes: tuple[str, ...]
    content_hash: str

    @classmethod
    def from_trial(
        cls,
        trial: R5RelativeValuePromotionTrial,
    ) -> R5RelativeValueTrialPerformance:
        """Derive every metric from sealed OOS observations."""

        target_growth = Decimal("1")
        benchmark_growth = Decimal("1")
        for observation in trial.observations:
            target_growth *= Decimal("1") + observation.target_net_return
            benchmark_growth *= Decimal("1") + observation.benchmark_net_return
        target_return = target_growth - Decimal("1")
        benchmark_return = benchmark_growth - Decimal("1")
        target_drawdown = max(item.target_maximum_drawdown for item in trial.observations)
        benchmark_drawdown = max(item.benchmark_maximum_drawdown for item in trial.observations)
        values: _PerformanceValues = {
            "observation_count": len(trial.observations),
            "target_compounded_net_return": target_return,
            "benchmark_compounded_net_return": benchmark_return,
            "excess_net_return": target_return - benchmark_return,
            "target_maximum_drawdown": target_drawdown,
            "benchmark_maximum_drawdown": benchmark_drawdown,
            "drawdown_increase": target_drawdown - benchmark_drawdown,
            "total_cost": sum(
                (item.target_cost for item in trial.observations),
                Decimal("0"),
            ),
            "liquidity_breach_ratio": Decimal(
                sum(item.liquidity_breached for item in trial.observations)
            )
            / Decimal(len(trial.observations)),
            "peak_capacity_utilization": max(
                item.capacity_utilization for item in trial.observations
            ),
            "total_realized_credit_loss": sum(
                (item.realized_credit_loss for item in trial.observations),
                Decimal("0"),
            ),
            "observation_hashes": tuple(item.content_hash for item in trial.observations),
        }
        digest = _canonical_hash(_performance_payload(**values))
        return cls(content_hash=digest, **values)

    def __post_init__(self) -> None:
        if isinstance(self.observation_count, bool) or self.observation_count < 1:
            raise ValueError("R5 performance observation_count must be positive")
        for field_name in (
            "target_compounded_net_return",
            "benchmark_compounded_net_return",
            "excess_net_return",
            "target_maximum_drawdown",
            "benchmark_maximum_drawdown",
            "drawdown_increase",
            "total_cost",
            "liquidity_breach_ratio",
            "peak_capacity_utilization",
            "total_realized_credit_loss",
        ):
            _require_finite(
                getattr(self, field_name),
                f"R5 trial performance {field_name}",
            )
        if self.excess_net_return != (
            self.target_compounded_net_return - self.benchmark_compounded_net_return
        ):
            raise ValueError("R5 performance excess return was substituted")
        if self.drawdown_increase != (
            self.target_maximum_drawdown - self.benchmark_maximum_drawdown
        ):
            raise ValueError("R5 performance drawdown increase was substituted")
        if self.total_cost < 0 or self.total_realized_credit_loss < 0:
            raise ValueError("R5 performance costs/losses cannot be negative")
        if not Decimal("0") <= self.liquidity_breach_ratio <= Decimal("1"):
            raise ValueError("R5 performance liquidity ratio must be within [0, 1]")
        if self.peak_capacity_utilization < 0:
            raise ValueError("R5 performance capacity utilization cannot be negative")
        if not self.observation_hashes or len(self.observation_hashes) != self.observation_count:
            raise ValueError("R5 performance observation seal family is incomplete")
        for digest in self.observation_hashes:
            require_sha256(digest, "R5 performance observation hash")
        require_sha256(self.content_hash, "R5 performance content_hash")
        if self.content_hash != r5_relative_value_trial_performance_hash(self):
            raise ValueError("R5 trial performance content hash mismatch")


def _performance_payload(
    *,
    observation_count: int,
    target_compounded_net_return: Decimal,
    benchmark_compounded_net_return: Decimal,
    excess_net_return: Decimal,
    target_maximum_drawdown: Decimal,
    benchmark_maximum_drawdown: Decimal,
    drawdown_increase: Decimal,
    total_cost: Decimal,
    liquidity_breach_ratio: Decimal,
    peak_capacity_utilization: Decimal,
    total_realized_credit_loss: Decimal,
    observation_hashes: tuple[str, ...],
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-trial-performance.v1",
        "observation_count": observation_count,
        "returns": [
            target_compounded_net_return,
            benchmark_compounded_net_return,
            excess_net_return,
        ],
        "drawdown": [
            target_maximum_drawdown,
            benchmark_maximum_drawdown,
            drawdown_increase,
        ],
        "cost_liquidity_capacity_credit": [
            total_cost,
            liquidity_breach_ratio,
            peak_capacity_utilization,
            total_realized_credit_loss,
        ],
        "observation_hashes": observation_hashes,
    }


def r5_relative_value_trial_performance_hash(
    performance: R5RelativeValueTrialPerformance,
) -> str:
    """Recompute the complete derived performance hash."""

    return _canonical_hash(
        _performance_payload(
            observation_count=performance.observation_count,
            target_compounded_net_return=performance.target_compounded_net_return,
            benchmark_compounded_net_return=performance.benchmark_compounded_net_return,
            excess_net_return=performance.excess_net_return,
            target_maximum_drawdown=performance.target_maximum_drawdown,
            benchmark_maximum_drawdown=performance.benchmark_maximum_drawdown,
            drawdown_increase=performance.drawdown_increase,
            total_cost=performance.total_cost,
            liquidity_breach_ratio=performance.liquidity_breach_ratio,
            peak_capacity_utilization=performance.peak_capacity_utilization,
            total_realized_credit_loss=performance.total_realized_credit_loss,
            observation_hashes=performance.observation_hashes,
        )
    )


@dataclass(frozen=True)
class R5RelativeValuePromotionGateOutcome:
    """One deterministic policy observation with auditable failure values."""

    gate_code: R5RelativeValuePromotionGateCode
    passes: bool
    reason_code: str
    observed_value: Decimal
    required_value: Decimal

    def __post_init__(self) -> None:
        if type(self.passes) is not bool:
            raise ValueError("R5 promotion gate passes must be boolean")
        expected_reason = "" if self.passes else f"{self.gate_code.value}_not_met"
        if self.reason_code != expected_reason:
            raise ValueError("R5 promotion gate reason does not match its state")
        _require_finite(self.observed_value, "R5 promotion gate observed_value")
        _require_finite(self.required_value, "R5 promotion gate required_value")


class _DecisionValues(TypedDict):
    decision_version: str
    scope: R5RelativeValuePromotionScope
    outcome: R5RelativeValuePromotionDecisionOutcome
    policy: R5RelativeValuePromotionPolicy
    trial: R5RelativeValuePromotionTrial
    performance: R5RelativeValueTrialPerformance
    gate_outcomes: tuple[R5RelativeValuePromotionGateOutcome, ...]
    reason_codes: tuple[str, ...]
    decided_at: datetime
    recorded_at: datetime
    valid_until: datetime


@dataclass(frozen=True)
class R5RelativeValuePromotionDecision:
    """Research-owned outcome derived from exact policy and trial evidence."""

    decision_id: str
    decision_version: str
    owner: str
    capability: str
    purpose: str
    scope: R5RelativeValuePromotionScope
    outcome: R5RelativeValuePromotionDecisionOutcome
    policy: R5RelativeValuePromotionPolicy
    trial: R5RelativeValuePromotionTrial
    performance: R5RelativeValueTrialPerformance
    gate_outcomes: tuple[R5RelativeValuePromotionGateOutcome, ...]
    reason_codes: tuple[str, ...]
    decided_at: datetime
    recorded_at: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        require_token(self.decision_version, "R5 promotion decision_version")
        if (
            self.owner != "research"
            or self.capability != "r5"
            or self.purpose != "fixed_income_relative_value_research"
        ):
            raise ValueError("R5 promotion decision authority is invalid")
        if (
            self.scope != self.policy.scope
            or self.scope != self.trial.scope
            or self.trial.policy_id != self.policy.policy_id
            or self.trial.policy_version != self.policy.policy_version
            or self.trial.policy_content_hash != self.policy.content_hash
            or self.trial.registration_id != self.policy.registration.registration_id
            or self.trial.registration_content_hash != self.policy.registration.content_hash
        ):
            raise ValueError("R5 promotion decision policy/trial scope was substituted")
        expected_performance = R5RelativeValueTrialPerformance.from_trial(self.trial)
        if self.performance != expected_performance:
            raise ValueError("R5 promotion decision performance was substituted")
        expected_gates = _evaluate_gates(self.policy, self.trial, expected_performance)
        if self.gate_outcomes != expected_gates:
            raise ValueError("R5 promotion decision gate outcomes were substituted")
        failures = tuple(sorted(item.reason_code for item in expected_gates if not item.passes))
        if self.outcome is R5RelativeValuePromotionDecisionOutcome.APPROVED:
            if failures or self.reason_codes != ("r5_relative_value_promotion_policy_satisfied",):
                raise ValueError("approved R5 outcome requires every gate")
        elif not failures or self.reason_codes != failures:
            raise ValueError("rejected R5 outcome reasons must match gate evidence")
        for field_name in ("decided_at", "recorded_at", "valid_until"):
            require_aware(
                getattr(self, field_name),
                f"R5 promotion decision {field_name}",
            )
        if not (
            self.trial.evaluated_at
            <= self.decided_at
            <= self.recorded_at
            < self.valid_until
            <= self.policy.active_until
            and self.valid_until <= self.trial.valid_until
        ):
            raise ValueError("R5 promotion decision validity is outside exact evidence")
        if not self.policy.is_active_at(self.decided_at) or not self.trial.is_active_at(
            self.decided_at
        ):
            raise ValueError("R5 promotion policy or trial is inactive at decision time")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R5 promotion decision must remain research-only")
        require_sha256(self.content_hash, "R5 promotion decision content_hash")
        expected = r5_relative_value_promotion_decision_hash(self)
        if self.content_hash != expected or self.decision_id != f"r5-rv-decision:{expected}":
            raise ValueError("R5 promotion decision content hash or identity mismatch")


def create_r5_relative_value_promotion_decision(
    *,
    policy: R5RelativeValuePromotionPolicy,
    trial: R5RelativeValuePromotionTrial,
    decided_at: datetime,
    recorded_at: datetime,
) -> R5RelativeValuePromotionDecision:
    """Derive metrics, gates, outcome and validity without caller values."""

    require_aware(decided_at, "R5 promotion decided_at")
    require_aware(recorded_at, "R5 promotion recorded_at")
    if not policy.is_active_at(decided_at):
        raise ValueError("R5 promotion policy is unavailable or inactive")
    if not trial.is_active_at(decided_at):
        raise ValueError("R5 promotion trial is unavailable or inactive")
    performance = R5RelativeValueTrialPerformance.from_trial(trial)
    gates = _evaluate_gates(policy, trial, performance)
    failures = tuple(sorted(item.reason_code for item in gates if not item.passes))
    outcome = (
        R5RelativeValuePromotionDecisionOutcome.APPROVED
        if not failures
        else R5RelativeValuePromotionDecisionOutcome.REJECTED
    )
    reasons = ("r5_relative_value_promotion_policy_satisfied",) if not failures else failures
    valid_until = r5_relative_value_promotion_decision_valid_until(
        policy=policy,
        trial=trial,
        decided_at=decided_at,
    )
    values: _DecisionValues = {
        "decision_version": "r5-relative-value-promotion-decision.v1",
        "scope": policy.scope,
        "outcome": outcome,
        "policy": policy,
        "trial": trial,
        "performance": performance,
        "gate_outcomes": gates,
        "reason_codes": reasons,
        "decided_at": decided_at,
        "recorded_at": recorded_at,
        "valid_until": valid_until,
    }
    digest = _canonical_hash(_decision_payload(**values))
    return R5RelativeValuePromotionDecision(
        decision_id=f"r5-rv-decision:{digest}",
        owner="research",
        capability="r5",
        purpose="fixed_income_relative_value_research",
        content_hash=digest,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_execute=True,
        **values,
    )


def r5_relative_value_promotion_decision_valid_until(
    *,
    policy: R5RelativeValuePromotionPolicy,
    trial: R5RelativeValuePromotionTrial,
    decided_at: datetime,
) -> datetime:
    """Return the minimum policy, trial and explicit duration boundary."""

    require_aware(decided_at, "R5 promotion validity decided_at")
    return min(
        policy.active_until,
        trial.valid_until,
        decided_at + timedelta(seconds=policy.decision_validity_seconds),
    )


def _gate(
    code: R5RelativeValuePromotionGateCode,
    *,
    observed: Decimal,
    required: Decimal,
    minimum: bool,
) -> R5RelativeValuePromotionGateOutcome:
    passes = observed >= required if minimum else observed <= required
    return R5RelativeValuePromotionGateOutcome(
        gate_code=code,
        passes=passes,
        reason_code="" if passes else f"{code.value}_not_met",
        observed_value=observed,
        required_value=required,
    )


def _evaluate_gates(
    policy: R5RelativeValuePromotionPolicy,
    trial: R5RelativeValuePromotionTrial,
    performance: R5RelativeValueTrialPerformance,
) -> tuple[R5RelativeValuePromotionGateOutcome, ...]:
    gates = (
        _gate(
            R5RelativeValuePromotionGateCode.TRIAL_READY,
            observed=(
                Decimal("1")
                if trial.state is R5RelativeValuePromotionTrialState.READY_FOR_POLICY_EVALUATION
                else Decimal("0")
            ),
            required=Decimal("1"),
            minimum=True,
        ),
        _gate(
            R5RelativeValuePromotionGateCode.MINIMUM_OBSERVATIONS,
            observed=Decimal(performance.observation_count),
            required=Decimal(policy.minimum_observation_count),
            minimum=True,
        ),
        _gate(
            R5RelativeValuePromotionGateCode.MINIMUM_COVERAGE,
            observed=trial.coverage_ratio,
            required=policy.minimum_coverage_ratio,
            minimum=True,
        ),
        _gate(
            R5RelativeValuePromotionGateCode.MINIMUM_EXCESS_NET_RETURN,
            observed=performance.excess_net_return,
            required=policy.minimum_excess_net_return,
            minimum=True,
        ),
        _gate(
            R5RelativeValuePromotionGateCode.MAXIMUM_DRAWDOWN_INCREASE,
            observed=performance.drawdown_increase,
            required=policy.maximum_drawdown_increase,
            minimum=False,
        ),
        _gate(
            R5RelativeValuePromotionGateCode.MAXIMUM_TOTAL_COST,
            observed=performance.total_cost,
            required=policy.maximum_total_cost,
            minimum=False,
        ),
        _gate(
            R5RelativeValuePromotionGateCode.MAXIMUM_LIQUIDITY_BREACH_RATIO,
            observed=performance.liquidity_breach_ratio,
            required=policy.maximum_liquidity_breach_ratio,
            minimum=False,
        ),
        _gate(
            R5RelativeValuePromotionGateCode.MAXIMUM_CAPACITY_UTILIZATION,
            observed=performance.peak_capacity_utilization,
            required=policy.maximum_capacity_utilization,
            minimum=False,
        ),
        _gate(
            R5RelativeValuePromotionGateCode.MAXIMUM_REALIZED_CREDIT_LOSS,
            observed=performance.total_realized_credit_loss,
            required=policy.maximum_realized_credit_loss,
            minimum=False,
        ),
    )
    return tuple(sorted(gates, key=lambda item: item.gate_code.value))


def _decision_payload(
    *,
    decision_version: str,
    scope: R5RelativeValuePromotionScope,
    outcome: R5RelativeValuePromotionDecisionOutcome,
    policy: R5RelativeValuePromotionPolicy,
    trial: R5RelativeValuePromotionTrial,
    performance: R5RelativeValueTrialPerformance,
    gate_outcomes: tuple[R5RelativeValuePromotionGateOutcome, ...],
    reason_codes: tuple[str, ...],
    decided_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-promotion-decision.v1",
        "identity": [decision_version, "research", "r5"],
        "scope": [scope.scope_id, scope.content_hash],
        "outcome": outcome.value,
        "policy": [policy.policy_id, policy.policy_version, policy.content_hash],
        "trial": [trial.trial_id, trial.trial_version, trial.content_hash],
        "performance": performance.content_hash,
        "gates": tuple(
            [
                item.gate_code.value,
                item.passes,
                item.reason_code,
                item.observed_value,
                item.required_value,
            ]
            for item in gate_outcomes
        ),
        "reason_codes": reason_codes,
        "window": [decided_at, recorded_at, valid_until],
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r5_relative_value_promotion_decision_hash(
    decision: R5RelativeValuePromotionDecision,
) -> str:
    """Recompute one exact derived R5 promotion decision hash."""

    return _canonical_hash(
        _decision_payload(
            decision_version=decision.decision_version,
            scope=decision.scope,
            outcome=decision.outcome,
            policy=decision.policy,
            trial=decision.trial,
            performance=decision.performance,
            gate_outcomes=decision.gate_outcomes,
            reason_codes=decision.reason_codes,
            decided_at=decision.decided_at,
            recorded_at=decision.recorded_at,
            valid_until=decision.valid_until,
        )
    )


__all__ = [
    "R5RelativeValuePromotionDecision",
    "R5RelativeValuePromotionDecisionOutcome",
    "R5RelativeValuePromotionGateCode",
    "R5RelativeValuePromotionGateOutcome",
    "R5RelativeValueTrialPerformance",
    "create_r5_relative_value_promotion_decision",
    "r5_relative_value_promotion_decision_hash",
    "r5_relative_value_promotion_decision_valid_until",
    "r5_relative_value_trial_performance_hash",
]
