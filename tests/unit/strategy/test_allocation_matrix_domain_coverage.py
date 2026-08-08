"""Focused branch coverage for allocation-policy domain invariants."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.strategy.domain import allocation_matrix as matrix
from apps.strategy.domain.allocation_matrix import (
    AllocationPolicyConfigurationError,
    AllocationPolicyDraft,
    AllocationPolicyEntry,
    AllocationPolicyIntegrityError,
    AllocationPolicySourceType,
    AllocationPolicyStatus,
    AllocationPolicyVersion,
    AllocationStatisticsStatus,
    AllocationTarget,
    AssetAllocation,
    PolicyAllocationAdjustment,
    PolicyLevel,
    RegimeType,
    RiskProfile,
    calculate_allocation_policy_content_hash,
    resolve_allocation_target,
)
from apps.strategy.domain.entities import (
    DecisionAction,
    DecisionResult,
    OrderIntent,
    OrderSide,
    RiskSnapshot,
    SizingResult,
)


def _entries(target: AllocationTarget | None = None) -> tuple[AllocationPolicyEntry, ...]:
    resolved_target = target or AllocationTarget(
        AssetAllocation(0.4, 0.3, 0.1, 0.2),
        "balanced",
    )
    return tuple(
        AllocationPolicyEntry(regime, risk, resolved_target)
        for regime in RegimeType
        for risk in RiskProfile
    )


def _adjustments(
    p1_equity_multiplier: float = 1.0,
) -> tuple[PolicyAllocationAdjustment, ...]:
    return tuple(
        PolicyAllocationAdjustment(
            level,
            p1_equity_multiplier if level is PolicyLevel.P1 else 1.0,
        )
        for level in PolicyLevel
    )


def _version(
    *,
    status: AllocationPolicyStatus = AllocationPolicyStatus.ACTIVE,
    entries: tuple[AllocationPolicyEntry, ...] | None = None,
    adjustments: tuple[PolicyAllocationAdjustment, ...] | None = None,
) -> AllocationPolicyVersion:
    resolved_entries = entries or _entries()
    resolved_adjustments = adjustments or _adjustments()
    return AllocationPolicyVersion(
        policy_key="strategic_asset_allocation",
        version=1,
        status=status,
        entries=resolved_entries,
        adjustments=resolved_adjustments,
        content_hash=calculate_allocation_policy_content_hash(
            resolved_entries,
            resolved_adjustments,
        ),
        source_type=AllocationPolicySourceType.HUMAN,
        change_reason="coverage",
        created_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "weights",
    (
        (float("nan"), 0.3, 0.2, 0.5),
        (-0.1, 0.4, 0.2, 0.5),
        (0.4, 0.3, 0.2, 0.2),
    ),
)
def test_asset_allocation_rejects_invalid_weights(weights: tuple[float, ...]) -> None:
    with pytest.raises(ValueError):
        AssetAllocation(*weights)


def test_allocation_target_statistics_validation_and_evidence_status() -> None:
    allocation = AssetAllocation(0.4, 0.3, 0.1, 0.2)
    for mutation in (
        {"expected_return": float("nan")},
        {"expected_volatility": -0.1},
        {"sharpe_ratio": float("inf")},
    ):
        with pytest.raises(ValueError):
            AllocationTarget(allocation, "reason", **mutation)
    with pytest.raises(ValueError, match="research_evidence_id"):
        AllocationTarget(
            allocation,
            "reason",
            statistics_status=AllocationStatisticsStatus.APPROVED_RESEARCH,
        )
    assert AllocationTarget(allocation, "reason").must_not_use_statistics_as_model_estimate
    approved = AllocationTarget(
        allocation,
        "reason",
        statistics_status=AllocationStatisticsStatus.APPROVED_RESEARCH,
        research_evidence_id="research-1",
    )
    assert approved.must_not_use_statistics_as_model_estimate is False


@pytest.mark.parametrize("value", (-1.0, float("nan")))
def test_policy_adjustment_rejects_invalid_multipliers(value: float) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        PolicyAllocationAdjustment(PolicyLevel.P0, value)
    with pytest.raises(ValueError, match="cannot exceed"):
        PolicyAllocationAdjustment(PolicyLevel.P0, 1.1)


def test_draft_identity_uniqueness_and_activation_completeness() -> None:
    entry = _entries()[0]
    adjustment = _adjustments()[0]
    for policy_key, reason in (("", "reason"), ("key", "")):
        with pytest.raises(ValueError):
            AllocationPolicyDraft(
                policy_key,
                (entry,),
                (adjustment,),
                AllocationPolicySourceType.HUMAN,
                reason,
            )
    with pytest.raises(ValueError, match="duplicate regime"):
        AllocationPolicyDraft(
            "key",
            (entry, entry),
            (adjustment,),
            AllocationPolicySourceType.HUMAN,
            "reason",
        )
    with pytest.raises(ValueError, match="duplicate policy"):
        AllocationPolicyDraft(
            "key",
            (entry,),
            (adjustment, adjustment),
            AllocationPolicySourceType.HUMAN,
            "reason",
        )
    with pytest.raises(AllocationPolicyConfigurationError, match="matrix is incomplete"):
        AllocationPolicyDraft(
            "key",
            (entry,),
            _adjustments(),
            AllocationPolicySourceType.HUMAN,
            "reason",
        ).validate_for_activation()
    with pytest.raises(AllocationPolicyConfigurationError, match="adjustments are incomplete"):
        AllocationPolicyDraft(
            "key",
            _entries(),
            (adjustment,),
            AllocationPolicySourceType.HUMAN,
            "reason",
        ).validate_for_activation()


def test_version_identity_time_and_hash_guards() -> None:
    valid = _version()
    for mutation in (
        {"policy_key": ""},
        {"version": 0},
        {"created_at": datetime(2026, 1, 1)},
        {"effective_at": datetime(2026, 1, 1)},
    ):
        with pytest.raises(ValueError):
            replace(valid, **mutation)
    with pytest.raises(AllocationPolicyIntegrityError):
        replace(valid, content_hash="0" * 64)
    draft = valid.as_draft(
        source_type=AllocationPolicySourceType.ROLLBACK,
        change_reason="rollback",
        created_by_id=7,
    )
    assert draft.based_on_version == valid.version


def test_resolution_rejects_invalid_context_and_covers_zero_other_weights() -> None:
    with pytest.raises(AllocationPolicyConfigurationError, match="not active"):
        resolve_allocation_target(
            _version(status=AllocationPolicyStatus.DRAFT), "Recovery", "moderate"
        )
    policy = _version()
    with pytest.raises(ValueError, match="invalid regime"):
        resolve_allocation_target(policy, "bad", "moderate")
    with pytest.raises(ValueError, match="invalid risk"):
        resolve_allocation_target(policy, "Recovery", "bad")
    with pytest.raises(ValueError, match="invalid policy"):
        resolve_allocation_target(policy, "Recovery", "moderate", "bad")

    target = AllocationTarget(
        AssetAllocation(0.8, 0.0, 0.2, 0.0),
        "equity and commodity",
        expected_return=0.1,
        expected_volatility=None,
        sharpe_ratio=0.5,
    )
    adjusted = resolve_allocation_target(
        _version(entries=_entries(target), adjustments=_adjustments(0.5)),
        "Recovery",
        "moderate",
        "P1",
    )
    assert adjusted.allocation.fixed_income == pytest.approx(0.2)
    assert adjusted.allocation.cash == pytest.approx(0.2)
    assert "政策收紧" in adjusted.reasoning
    assert adjusted.expected_return == pytest.approx(0.1)
    assert adjusted.expected_volatility is None


def test_canonical_number_and_order_intent_edges() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        matrix._canonical_number(float("inf"), decimal_places=6)

    decision = DecisionResult(DecisionAction.ALLOW, [], "allowed")
    sizing = SizingResult(1000, 100, 0.1, "fixed", "coverage")
    risk = RiskSnapshot(10000, 5000, 5000, 0, 10, 20, "Recovery", 0.8)
    base = {
        "intent_id": "intent-1",
        "strategy_id": 1,
        "portfolio_id": 1,
        "symbol": "000001.SZ",
        "side": OrderSide.BUY,
        "qty": 100,
        "decision": decision,
        "sizing": sizing,
        "risk_snapshot": risk,
    }
    assert OrderIntent(**base).idempotency_key == "intent-1"
    with pytest.raises(ValueError, match="qty"):
        OrderIntent(**{**base, "qty": 0})
    with pytest.raises(ValueError, match="limit_price"):
        OrderIntent(**{**base, "limit_price": 0})
    with pytest.raises(ValueError, match="intent_id"):
        OrderIntent(**{**base, "intent_id": ""})
