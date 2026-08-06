"""Unit coverage for derived R4 Research promotion decisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from inspect import signature

import pytest

from apps.research.domain.r4_promotion_decision import (
    R4PromotionDecisionOutcome,
    R4PromotionGateCode,
    create_r4_promotion_decision,
    r4_promotion_decision_valid_until,
)
from apps.research.domain.r4_promotion_trial import R4PromotionTrialState
from tests.unit.portfolio.macro_risk_rolling_factories import build_study
from tests.unit.research.r4_promotion_factories import (
    DECIDED_AT,
    portfolio_record,
    portfolio_record_seal,
    promotion_decision,
    promotion_policy,
    promotion_trial,
)


def test_approved_outcome_relative_metrics_and_validity_are_derived() -> None:
    policy = promotion_policy()
    trial = promotion_trial(policy=policy)

    decision = promotion_decision(policy=policy, trial=trial)

    assert decision.outcome is R4PromotionDecisionOutcome.APPROVED
    assert decision.reason_codes == ("r4_promotion_policy_satisfied",)
    assert len(decision.relative_method_evidence) == 2
    assert len(decision.gate_outcomes) == 12
    assert all(item.passes for item in decision.gate_outcomes)
    assert decision.valid_until == r4_promotion_decision_valid_until(
        policy=policy,
        trial=trial,
        as_of=DECIDED_AT,
    )
    assert decision.valid_until == min(
        policy.active_until,
        trial.portfolio_record.valid_until,
        trial.current_r3_attestation.effective_valid_until,
        DECIDED_AT + timedelta(seconds=policy.decision_validity_seconds),
    )
    for item in decision.relative_method_evidence:
        assert item.target_net_return == (
            next(
                value
                for value in trial.portfolio_record.method_summaries
                if value.method is item.target_method
            ).compounded_gross_return
            - item.target_cost
        )
        assert item.target_volatility >= 0


def test_threshold_failure_produces_auditable_rejected_decision() -> None:
    policy = promotion_policy(minimum_relative_net_return=Decimal("0.5"))
    trial = promotion_trial(policy=policy)

    decision = promotion_decision(policy=policy, trial=trial)

    assert decision.outcome is R4PromotionDecisionOutcome.REJECTED
    assert decision.reason_codes
    assert any("relative_net_return" in item for item in decision.reason_codes)
    assert any(
        item.gate_code is R4PromotionGateCode.RELATIVE_NET_RETURN and not item.passes
        for item in decision.gate_outcomes
    )
    assert decision.content_hash


def test_blocked_trial_is_rejected_but_remains_hash_sealed_and_auditable() -> None:
    blocked_record = portfolio_record(study=build_study(minimum_regime_windows=3))
    trial = promotion_trial(record_seal=portfolio_record_seal(record=blocked_record))

    decision = promotion_decision(trial=trial)

    assert trial.state is R4PromotionTrialState.BLOCKED
    assert decision.outcome is R4PromotionDecisionOutcome.REJECTED
    assert "trial_ready_not_met" in decision.reason_codes
    assert decision.content_hash


def test_outcome_gates_reasons_and_relative_values_cannot_be_caller_substituted() -> None:
    decision = promotion_decision()

    assert "outcome" not in signature(create_r4_promotion_decision).parameters
    assert "gate_outcomes" not in signature(create_r4_promotion_decision).parameters
    with pytest.raises(ValueError, match="approved R4 promotion"):
        replace(decision, reason_codes=("caller_approved",))
    with pytest.raises(ValueError, match="gate outcomes were substituted"):
        replace(decision, gate_outcomes=decision.gate_outcomes[:-1])
    with pytest.raises(ValueError, match="relative method evidence was substituted"):
        replace(decision, relative_method_evidence=decision.relative_method_evidence[:-1])
