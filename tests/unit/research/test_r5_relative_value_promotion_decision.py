"""Derived R5 trial metrics, gates, decision outcome and validity."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.research.domain.r5_relative_value_promotion_decision import (
    R5RelativeValuePromotionDecisionOutcome,
    create_r5_relative_value_promotion_decision,
)
from tests.unit.research.r5_relative_value_promotion_factories import (
    BASE_TIME,
    make_policy,
    make_trial,
)


def test_decision_derives_performance_gates_outcome_and_validity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No caller-provided metric, decision or validity value is accepted."""

    policy = make_policy()
    trial = make_trial(monkeypatch, policy=policy)
    decided_at = BASE_TIME + timedelta(hours=3, minutes=1)
    decision = create_r5_relative_value_promotion_decision(
        policy=policy,
        trial=trial,
        decided_at=decided_at,
        recorded_at=decided_at + timedelta(minutes=1),
    )

    assert decision.outcome is R5RelativeValuePromotionDecisionOutcome.APPROVED
    assert decision.decision_id == f"r5-rv-decision:{decision.content_hash}"
    assert decision.performance.excess_net_return > Decimal("0")
    assert all(item.passes for item in decision.gate_outcomes)
    assert decision.valid_until == min(
        policy.active_until,
        trial.valid_until,
        decided_at + timedelta(seconds=policy.decision_validity_seconds),
    )
    assert decision.research_only
    assert decision.must_not_use_for_decision
    assert decision.must_not_execute


def test_threshold_failure_is_derived_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stricter preregistered gate rejects without caller reason injection."""

    policy = make_policy(minimum_excess_net_return=Decimal("0.50"))
    trial = make_trial(monkeypatch, policy=policy)
    decision = create_r5_relative_value_promotion_decision(
        policy=policy,
        trial=trial,
        decided_at=BASE_TIME + timedelta(hours=3, minutes=1),
        recorded_at=BASE_TIME + timedelta(hours=3, minutes=2),
    )

    assert decision.outcome is R5RelativeValuePromotionDecisionOutcome.REJECTED
    assert "minimum_excess_net_return_not_met" in decision.reason_codes


def test_caller_cannot_substitute_gate_outcome_or_safety_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hash-only reconstruction cannot turn a rejection into approval or execution."""

    policy = make_policy(minimum_excess_net_return=Decimal("0.50"))
    trial = make_trial(monkeypatch, policy=policy)
    decision = create_r5_relative_value_promotion_decision(
        policy=policy,
        trial=trial,
        decided_at=BASE_TIME + timedelta(hours=3, minutes=1),
        recorded_at=BASE_TIME + timedelta(hours=3, minutes=2),
    )
    with pytest.raises(ValueError, match="outcome|gate|hash"):
        replace(decision, outcome=R5RelativeValuePromotionDecisionOutcome.APPROVED)
    with pytest.raises(ValueError, match="research-only"):
        replace(decision, must_not_execute=False)
