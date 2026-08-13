"""Django 5.2 component coverage for Portfolio owner reader adapters."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import django
import pytest
from django.utils import timezone

from apps.portfolio.application.transition_plan_inactive_approval import (
    TransitionPlanInactiveApprovalSubject,
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
)
from apps.portfolio.infrastructure.repositories import PortfolioTransitionPlanRepository
from apps.portfolio.infrastructure.transition_models import PortfolioTransitionPlanModel
from apps.portfolio.infrastructure.transition_plan_inactive_approval_repository import (
    DjangoTransitionPlanInactiveApprovalRepository,
)
from apps.portfolio.transition_plan_owner_readers_composition import (
    build_django_transition_plan_owner_reader_runtime,
)


def _actor(user_id: int) -> TransitionPlanApprovalActor:
    return TransitionPlanApprovalActor(
        actor_id=f"user:{user_id}", user_id=user_id, role="portfolio_owner"
    )


def _plan() -> TransitionPlan:
    now = timezone.now()
    return TransitionPlan(
        plan_id="owner-reader-plan-1",
        idempotency_key="owner-reader-idem-1",
        account_id="account:7",
        decision_snapshot_id="decision-1",
        portfolio_snapshot_id="portfolio-1",
        target_portfolio_id="target-1",
        as_of_time=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
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


@pytest.mark.django_db(transaction=True)
def test_django_owner_runtime_reads_exact_plan_row_and_identity_receipt() -> None:
    assert django.VERSION[:2] == (5, 2)
    plan = _plan()
    PortfolioTransitionPlanRepository().save(plan)
    approved_at = timezone.now()
    PortfolioTransitionPlanModel._default_manager.filter(plan_id=plan.plan_id).update(
        approved_at=approved_at
    )
    subject = TransitionPlanInactiveApprovalSubject(
        subject_id="owner-reader-subject-1",
        subject_version="v1",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_content_hash=PortfolioTransitionPlanModel._default_manager.get(
            plan_id=plan.plan_id
        ).immutable_payload_hash,
        account_id=plan.account_id,
        decision_snapshot_id=plan.decision_snapshot_id,
        requested_by=_actor(11),
        requested_at=approved_at,
        valid_until=plan.expires_at,
    )
    receipt = TransitionPlanApprovalReceipt(
        receipt_id="owner-reader-receipt-1",
        receipt_version="v1",
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        subject_content_hash=subject.content_hash,
        plan_id=subject.plan_id,
        plan_version=subject.plan_version,
        plan_content_hash=subject.plan_content_hash,
        account_id=subject.account_id,
        decision_snapshot_id=subject.decision_snapshot_id,
        requested_by=subject.requested_by,
        approved_by=_actor(12),
        issued_at=approved_at,
        valid_until=subject.valid_until,
    )
    ledger = DjangoTransitionPlanInactiveApprovalRepository()
    with ledger.atomic():
        ledger.append_subject(subject, recorded_at=approved_at)
        ledger.append(
            receipt,
            subject=subject,
            recorded_at=approved_at,
        )
    cutoff = timezone.now()
    runtime = build_django_transition_plan_owner_reader_runtime()

    plan_row = runtime.plan_order_reader.execute(
        GetExactActiveTransitionPlanOrderQuery(
            plan_id=plan.plan_id,
            plan_version=plan.version,
            order_ordinal=0,
            as_of=cutoff,
        )
    )
    receipt_row = runtime.inactive_receipt_reader.execute(
        GetExactInactiveTransitionPlanApprovalReceiptQuery(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=cutoff,
        )
    )

    assert plan_row.content_hash == subject.plan_content_hash
    assert plan_row.order_ordinal == 0
    assert receipt_row.content_hash == receipt.content_hash
    assert receipt_row.recorded_at == receipt.issued_at
    assert receipt_row.execution_permission == "inactive"
    assert receipt_row.must_not_execute is True
