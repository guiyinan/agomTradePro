"""Pure factory tests for Portfolio transition-plan owner reader composition."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.portfolio.application.transition_plan_inactive_approval import (
    TransitionPlanDefinition,
)
from apps.portfolio.application.transition_plan_inactive_receipt_reader import (
    GetExactInactiveTransitionPlanApprovalReceiptQuery,
)
from apps.portfolio.application.transition_plan_order_reader import (
    GetExactActiveTransitionPlanOrderQuery,
)
from apps.portfolio.domain.entities import OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_integrity import (
    TransitionPlanApprovalActor,
    TransitionPlanApprovalReceipt,
    transition_plan_content_hash_v1,
)
from apps.portfolio.transition_plan_owner_readers_composition import (
    TransitionPlanOwnerReadersCompositionUnavailable,
    build_transition_plan_owner_reader_runtime,
)

PLAN_AT = datetime(2026, 8, 13, 8, tzinfo=UTC)
RECORDED_AT = PLAN_AT + timedelta(minutes=1)
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


def _definition() -> TransitionPlanDefinition:
    plan = _plan()
    return TransitionPlanDefinition(
        plan=plan,
        content_hash=transition_plan_content_hash_v1(plan),
        recorded_at=RECORDED_AT,
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
        issued_at=RECORDED_AT,
    )


class PlanProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, datetime]] = []

    def get_exact(
        self, *, plan_id: str, plan_version: int, as_of: datetime
    ) -> TransitionPlanDefinition | None:
        self.calls.append((plan_id, plan_version, as_of))
        return _definition()


class ReceiptRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, datetime]] = []

    def get_receipt_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> TransitionPlanApprovalReceipt | None:
        self.calls.append((receipt_id, receipt_version, as_of))
        return _receipt()


def test_injected_factory_builds_both_owner_readers_and_preserves_alias_cutoff() -> None:
    aliases: list[tuple[str, str]] = []
    plan_provider = PlanProvider()
    receipt_repository = ReceiptRepository()
    runtime = build_transition_plan_owner_reader_runtime(
        using="portfolio_replica",
        plan_provider_factory=lambda using: (aliases.append(("plan", using)) or plan_provider),
        receipt_repository_factory=lambda using: (
            aliases.append(("receipt", using)) or receipt_repository
        ),
    )

    plan_row = runtime.plan_order_reader.execute(
        GetExactActiveTransitionPlanOrderQuery(
            plan_id="plan-1",
            plan_version=1,
            order_ordinal=0,
            as_of=RECORDED_AT,
        )
    )
    receipt = runtime.inactive_receipt_reader.execute(
        GetExactInactiveTransitionPlanApprovalReceiptQuery(
            receipt_id="receipt-1", receipt_version="v1", as_of=RECORDED_AT
        )
    )

    assert aliases == [
        ("plan", "portfolio_replica"),
        ("receipt", "portfolio_replica"),
    ]
    assert plan_provider.calls == [("plan-1", 1, RECORDED_AT)]
    assert receipt_repository.calls == [("receipt-1", "v1", RECORDED_AT)]
    assert plan_row.owner == receipt.owner == "portfolio"
    assert receipt.execution_permission == "inactive"
    assert receipt.must_not_execute is True


@pytest.mark.parametrize(
    ("plan_factory", "receipt_factory"),
    [
        (None, None),
        (lambda using: PlanProvider(), None),
        (None, lambda using: ReceiptRepository()),
    ],
)
def test_missing_owner_factory_fails_before_constructing_partial_runtime(
    plan_factory: object, receipt_factory: object
) -> None:
    with pytest.raises(TransitionPlanOwnerReadersCompositionUnavailable, match="unconfigured"):
        build_transition_plan_owner_reader_runtime(
            plan_provider_factory=plan_factory,  # type: ignore[arg-type]
            receipt_repository_factory=receipt_factory,  # type: ignore[arg-type]
        )


def test_composition_import_is_pure_until_explicit_django_builder_call() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "portfolio"
        / "transition_plan_owner_readers_composition.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    top_level_imports = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(".infrastructure" in module for module in top_level_imports)
