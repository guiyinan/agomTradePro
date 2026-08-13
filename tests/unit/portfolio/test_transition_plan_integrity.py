from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.portfolio.domain.entities import ConstraintDecision, OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_integrity import (
    TransitionPlanApprovalActor,
    TransitionPlanApprovalReceipt,
    canonical_transition_plan_bytes_v1,
    transition_plan_content_hash_v1,
    transition_plan_hash_matches_v1,
    validate_transition_plan_for_approval_receipt,
)

NOW = datetime(2026, 8, 13, 10, 30, 1, 123456, tzinfo=timezone(timedelta(hours=8)))


def _plan(**changes: object) -> TransitionPlan:
    constraint = ConstraintDecision("cash", "600000.SH", True, 100, 80, "现金上限")
    order = OrderDraft(
        asset_code="600000.SH",
        side="buy",
        quantity=80,
        reference_price=Decimal("10.00"),
        estimated_fee=Decimal("2.00"),
        status="partial",
        remaining_quantity=20,
        constraints=(constraint,),
    )
    values: dict[str, object] = {
        "plan_id": "plan-1",
        "idempotency_key": "idem-1",
        "account_id": "7",
        "decision_snapshot_id": "decision-1",
        "portfolio_snapshot_id": "portfolio-1",
        "target_portfolio_id": "target-1",
        "as_of_time": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "orders": (order,),
        "constraints": (constraint,),
        "cash_before": Decimal("1000.00"),
        "cash_after": Decimal("198.00"),
        "status": "APPROVED",
        "version": 1,
        "metadata": {"planning_policy_version": "policy-v1"},
    }
    values.update(changes)
    return TransitionPlan(**values)  # type: ignore[arg-type]


def test_v1_bytes_match_the_historical_infrastructure_algorithm() -> None:
    plan = _plan()
    payload = {
        "account_id": plan.account_id,
        "decision_snapshot_id": plan.decision_snapshot_id,
        "portfolio_snapshot_id": plan.portfolio_snapshot_id,
        "target_portfolio_id": plan.target_portfolio_id,
        "as_of_time": plan.as_of_time.isoformat(),
        "expires_at": plan.expires_at.isoformat(),
        "orders": [
            {
                "asset_code": "600000.SH",
                "side": "buy",
                "quantity": 80,
                "reference_price": "10.00",
                "estimated_fee": "2.00",
                "status": "partial",
                "remaining_quantity": 20,
                "constraints": [
                    {
                        "rule_code": "cash",
                        "asset_code": "600000.SH",
                        "allowed": True,
                        "original_quantity": 100,
                        "allowed_quantity": 80,
                        "reason": "现金上限",
                    }
                ],
            }
        ],
        "constraints": [
            {
                "rule_code": "cash",
                "asset_code": "600000.SH",
                "allowed": True,
                "original_quantity": 100,
                "allowed_quantity": 80,
                "reason": "现金上限",
            }
        ],
        "cash_before": "1000.00",
        "cash_after": "198.00",
        "planning_policy_version": "policy-v1",
        "version": 1,
    }
    expected = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert canonical_transition_plan_bytes_v1(plan) == expected
    assert transition_plan_content_hash_v1(plan) == hashlib.sha256(expected).hexdigest()


def test_v1_preserves_historical_decimal_and_timezone_byte_semantics() -> None:
    original = _plan()
    decimal_changed = replace(original, cash_before=Decimal("1000.0"))
    timezone_changed = replace(original, as_of_time=original.as_of_time.astimezone(timezone.utc))
    assert transition_plan_content_hash_v1(decimal_changed) != transition_plan_content_hash_v1(
        original
    )
    assert transition_plan_content_hash_v1(timezone_changed) != transition_plan_content_hash_v1(
        original
    )


def test_lifecycle_fields_do_not_change_the_immutable_payload_hash() -> None:
    original = _plan()
    assert transition_plan_content_hash_v1(replace(original, status="EXECUTED")) == (
        transition_plan_content_hash_v1(original)
    )


@pytest.mark.parametrize(
    "plan",
    [
        _plan(as_of_time=datetime(2026, 8, 13, 10)),
        _plan(version=True),
        _plan(cash_before=Decimal("NaN")),
        _plan(metadata={"planning_policy_version": "policy-v1", "extra": "bad"}),
        _plan(orders=(replace(_plan().orders[0], side="hold"),)),
        _plan(constraints=()),
    ],
)
def test_receipt_eligibility_fails_closed_on_invalid_plan(plan: TransitionPlan) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_transition_plan_for_approval_receipt(plan)


def test_inactive_approval_receipt_is_sealed_and_never_executable() -> None:
    plan = _plan()
    actor = TransitionPlanApprovalActor(actor_id="user:19", user_id=19, role="owner")
    receipt = TransitionPlanApprovalReceipt.create(
        receipt_id="plan-approval:plan-1:v1",
        receipt_version="v1",
        plan=plan,
        approved_by=actor,
        issued_at=NOW + timedelta(minutes=1),
    )
    assert receipt.plan_content_hash == transition_plan_content_hash_v1(plan)
    assert receipt.must_not_execute is True
    assert receipt.execution_permission == "inactive"
    assert receipt.to_payload()["must_not_execute"] is True
    assert transition_plan_hash_matches_v1(plan, receipt.plan_content_hash)


def test_receipt_rejects_non_staff_actor_tamper_and_inverted_clock() -> None:
    with pytest.raises(ValueError, match="human staff"):
        TransitionPlanApprovalActor(actor_id="service:1", user_id=1, role="service", kind="service")
    actor = TransitionPlanApprovalActor(actor_id="user:19", user_id=19, role="owner")
    with pytest.raises(ValueError, match="validity window"):
        TransitionPlanApprovalReceipt.create(
            receipt_id="plan-approval:plan-1:v1",
            receipt_version="v1",
            plan=_plan(expires_at=NOW + timedelta(seconds=30)),
            approved_by=actor,
            issued_at=NOW + timedelta(minutes=1),
        )
    receipt = TransitionPlanApprovalReceipt.create(
        receipt_id="plan-approval:plan-1:v1",
        receipt_version="v1",
        plan=_plan(),
        approved_by=actor,
        issued_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="content_hash"):
        replace(receipt, content_hash="b" * 64)
