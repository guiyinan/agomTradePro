"""Pure tests for the Portfolio-owned inactive approval receipt reader."""

from __future__ import annotations

import ast
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.portfolio.application.transition_plan_inactive_receipt_reader import (
    ExactInactiveTransitionPlanApprovalReceipt,
    GetExactInactiveTransitionPlanApprovalReceipt,
    GetExactInactiveTransitionPlanApprovalReceiptQuery,
    TransitionPlanInactiveReceiptReaderCorruption,
    TransitionPlanInactiveReceiptReaderUnavailable,
)
from apps.portfolio.domain.entities import OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_integrity import (
    TransitionPlanApprovalActor,
    TransitionPlanApprovalReceipt,
)

PLAN_AT = datetime(2026, 8, 13, 8, tzinfo=UTC)
ISSUED_AT = PLAN_AT + timedelta(minutes=1)
EXPIRES_AT = PLAN_AT + timedelta(hours=1)


def _actor(user_id: int) -> TransitionPlanApprovalActor:
    return TransitionPlanApprovalActor(
        actor_id=f"user:{user_id}", user_id=user_id, role="portfolio_owner"
    )


def _plan() -> TransitionPlan:
    return TransitionPlan(
        plan_id="plan-1",
        idempotency_key="idem-1",
        account_id="account:7",
        decision_snapshot_id="decision-1",
        portfolio_snapshot_id="portfolio-1",
        target_portfolio_id="target-1",
        as_of_time=PLAN_AT,
        expires_at=EXPIRES_AT,
        orders=(
            OrderDraft(
                asset_code="600000.SH",
                side="buy",
                quantity=10,
                reference_price=Decimal("10.00"),
                estimated_fee=Decimal("1.00"),
                status="draft",
            ),
        ),
        constraints=(),
        cash_before=Decimal("1000.00"),
        cash_after=Decimal("899.00"),
        status="APPROVED",
        version=1,
        metadata={"planning_policy_version": "policy-v1"},
    )


def _receipt() -> TransitionPlanApprovalReceipt:
    return TransitionPlanApprovalReceipt.create(
        receipt_id="receipt-1",
        receipt_version="v1",
        subject_id="subject-1",
        subject_version="v1",
        subject_content_hash="a" * 64,
        requested_by=_actor(11),
        plan=_plan(),
        approved_by=_actor(12),
        issued_at=ISSUED_AT,
    )


class ReceiptRepository:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[tuple[str, str, datetime]] = []

    def get_receipt_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> TransitionPlanApprovalReceipt | None:
        self.calls.append((receipt_id, receipt_version, as_of))
        return self.value  # type: ignore[return-value]


def _query(*, as_of: datetime = ISSUED_AT) -> GetExactInactiveTransitionPlanApprovalReceiptQuery:
    return GetExactInactiveTransitionPlanApprovalReceiptQuery(
        receipt_id="receipt-1", receipt_version="v1", as_of=as_of
    )


def test_id_only_reader_projects_all_sealed_bindings_at_the_same_cutoff() -> None:
    receipt = _receipt()
    repository = ReceiptRepository(receipt)

    result = GetExactInactiveTransitionPlanApprovalReceipt(repository).execute(_query())

    assert result == ExactInactiveTransitionPlanApprovalReceipt(
        receipt_id=receipt.receipt_id,
        receipt_version=receipt.receipt_version,
        content_hash=receipt.content_hash,
        subject_id=receipt.subject_id,
        subject_version=receipt.subject_version,
        subject_content_hash=receipt.subject_content_hash,
        plan_id=receipt.plan_id,
        plan_version=receipt.plan_version,
        plan_content_hash=receipt.plan_content_hash,
        account_id=receipt.account_id,
        decision_snapshot_id=receipt.decision_snapshot_id,
        issued_at=receipt.issued_at,
        recorded_at=receipt.issued_at,
        valid_until=receipt.valid_until,
    )
    assert result.owner == "portfolio"
    assert result.capability == "transition_plan_inactive_approval"
    assert result.schema == "portfolio-transition-plan-approval-receipt.v1"
    assert result.approval_state == "approved"
    assert result.execution_permission == "inactive"
    assert result.must_not_execute is True
    assert repository.calls == [("receipt-1", "v1", ISSUED_AT)]


def test_query_surface_is_id_only_and_rejects_noncanonical_inputs() -> None:
    assert {field.name for field in fields(GetExactInactiveTransitionPlanApprovalReceiptQuery)} == {
        "receipt_id",
        "receipt_version",
        "as_of",
    }
    with pytest.raises(ValueError, match="receipt_id"):
        GetExactInactiveTransitionPlanApprovalReceiptQuery(
            receipt_id="bad receipt", receipt_version="v1", as_of=ISSUED_AT
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        GetExactInactiveTransitionPlanApprovalReceiptQuery(
            receipt_id="receipt-1",
            receipt_version="v1",
            as_of=datetime(2026, 8, 13, 8),
        )


def test_reader_reports_missing_and_inactive_window_boundaries_as_unavailable() -> None:
    with pytest.raises(TransitionPlanInactiveReceiptReaderUnavailable, match="unavailable"):
        GetExactInactiveTransitionPlanApprovalReceipt(ReceiptRepository(None)).execute(_query())

    for as_of in (ISSUED_AT - timedelta(microseconds=1), EXPIRES_AT):
        with pytest.raises(TransitionPlanInactiveReceiptReaderUnavailable, match="unavailable"):
            GetExactInactiveTransitionPlanApprovalReceipt(ReceiptRepository(_receipt())).execute(
                _query(as_of=as_of)
            )


def test_reader_rejects_type_and_identity_substitution() -> None:
    with pytest.raises(TransitionPlanInactiveReceiptReaderCorruption, match="type"):
        GetExactInactiveTransitionPlanApprovalReceipt(ReceiptRepository(object())).execute(_query())

    substituted = object.__new__(TransitionPlanApprovalReceipt)
    for field in fields(TransitionPlanApprovalReceipt):
        value = getattr(_receipt(), field.name)
        object.__setattr__(
            substituted, field.name, "receipt-other" if field.name == "receipt_id" else value
        )
    with pytest.raises(TransitionPlanInactiveReceiptReaderCorruption, match="identity"):
        GetExactInactiveTransitionPlanApprovalReceipt(ReceiptRepository(substituted)).execute(
            _query()
        )


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("owner", "broker_execution"),
        ("schema", "portfolio-transition-plan-approval-receipt.v2"),
        ("approval_state", "revoked"),
        ("execution_permission", "active"),
        ("content_hash", ""),
    ],
)
def test_reader_revalidates_authority_schema_state_and_seal(
    field_name: str, bad_value: object
) -> None:
    receipt = _receipt()
    object.__setattr__(receipt, field_name, bad_value)

    with pytest.raises(TransitionPlanInactiveReceiptReaderCorruption, match="invalid"):
        GetExactInactiveTransitionPlanApprovalReceipt(ReceiptRepository(receipt)).execute(_query())


def test_application_reader_has_no_infrastructure_or_broker_dependency() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "portfolio"
        / "application"
        / "transition_plan_inactive_receipt_reader.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(".infrastructure" in module for module in modules)
    assert not any(module.startswith("apps.broker_execution") for module in modules)
