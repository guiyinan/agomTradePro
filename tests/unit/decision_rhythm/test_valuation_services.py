"""Unit tests for valuation pricing and execution approval domain services."""

from decimal import Decimal

import pytest

from apps.decision_rhythm.domain.entities import (
    ApprovalStatus,
    RecommendationSide,
    ValuationMethod,
    create_execution_approval_request,
    create_investment_recommendation,
    create_valuation_snapshot,
)
from apps.decision_rhythm.domain.services import (
    ApprovalStatusStateMachine,
    ExecutionApprovalService,
    ValuationSnapshotService,
)


def _snapshot() -> object:
    return create_valuation_snapshot(
        security_code="000001.SH",
        valuation_method=ValuationMethod.COMPOSITE.value,
        fair_value=Decimal("10"),
        entry_price_low=Decimal("9.5"),
        entry_price_high=Decimal("10.5"),
        target_price_low=Decimal("11"),
        target_price_high=Decimal("12"),
        stop_loss_price=Decimal("8.8"),
        input_parameters={"source": "unit_test"},
    )


def test_create_snapshot_has_price_bands():
    service = ValuationSnapshotService()
    snapshot = service.create_snapshot(
        security_code="000001.SH",
        valuation_method=ValuationMethod.COMPOSITE.value,
        fair_value=Decimal("10"),
        current_price=Decimal("9.8"),
        input_parameters={"source": "unit_test"},
    )

    assert snapshot.entry_price_low < snapshot.entry_price_high
    assert snapshot.target_price_low < snapshot.target_price_high
    assert snapshot.stop_loss_price < snapshot.entry_price_low


def test_create_legacy_snapshot_is_marked_legacy():
    service = ValuationSnapshotService()
    snapshot = service.create_legacy_snapshot(
        security_code="000001.SH",
        estimated_fair_value=Decimal("9.9"),
        current_price=Decimal("10"),
    )

    assert snapshot.is_legacy is True
    assert snapshot.valuation_method == "LEGACY"


def test_recommendation_buy_price_validation():
    recommendation = create_investment_recommendation(
        security_code="000001.SH",
        side=RecommendationSide.BUY.value,
        confidence=0.8,
        valuation_snapshot=_snapshot(),
        account_id="acc-1",
    )

    ok, _ = recommendation.validate_buy_price(Decimal("10.2"))
    bad, _ = recommendation.validate_buy_price(Decimal("10.8"))

    assert ok is True
    assert bad is False


def test_execution_approval_service_approve_and_reject():
    recommendation = create_investment_recommendation(
        security_code="000001.SH",
        side=RecommendationSide.BUY.value,
        confidence=0.9,
        valuation_snapshot=_snapshot(),
        account_id="acc-1",
    )

    approval_request = create_execution_approval_request(
        recommendation=recommendation,
        account_id="acc-1",
        risk_check_results={"quota": {"passed": True}},
        regime_source="V2_CALCULATION",
        market_price_at_review=Decimal("10.1"),
    )

    service = ExecutionApprovalService()
    can_approve, _ = service.can_approve(approval_request, Decimal("10.1"))
    approved = service.approve(approval_request, reviewer_comments="ok", market_price=Decimal("10.1"))

    assert can_approve is True
    assert approved.approval_status == ApprovalStatus.APPROVED

    rejected = service.reject(approval_request, reviewer_comments="risk")
    assert rejected.approval_status == ApprovalStatus.REJECTED


def test_approval_state_machine_transitions():
    assert ApprovalStatusStateMachine.can_transition(ApprovalStatus.PENDING, ApprovalStatus.APPROVED)
    assert ApprovalStatusStateMachine.can_transition(ApprovalStatus.APPROVED, ApprovalStatus.EXECUTED)
    assert not ApprovalStatusStateMachine.can_transition(ApprovalStatus.REJECTED, ApprovalStatus.APPROVED)


@pytest.mark.parametrize(
    "from_status,to_status,expected",
    [
        (ApprovalStatus.DRAFT, ApprovalStatus.PENDING, True),
        (ApprovalStatus.PENDING, ApprovalStatus.REJECTED, True),
        (ApprovalStatus.EXECUTED, ApprovalStatus.PENDING, False),
    ],
)
def test_validate_transition(from_status, to_status, expected):
    ok, _ = ApprovalStatusStateMachine.validate_transition(from_status, to_status)
    assert ok is expected
