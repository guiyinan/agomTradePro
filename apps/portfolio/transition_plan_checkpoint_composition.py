"""Re-read the Portfolio plan and its original receipt at a Broker write checkpoint."""

from __future__ import annotations

from datetime import datetime

from django.db import connections

from apps.portfolio.application.transition_plan_inactive_receipt_reader import (
    ExactInactiveTransitionPlanApprovalReceipt,
    GetExactInactiveTransitionPlanApprovalReceiptQuery,
)
from apps.portfolio.application.transition_plan_order_reader import (
    ExactActiveTransitionPlanOrderDefinition,
    GetExactActiveTransitionPlanOrderQuery,
)
from apps.portfolio.infrastructure.transition_models import PortfolioTransitionPlanModel
from apps.portfolio.infrastructure.transition_plan_inactive_approval_models import (
    TransitionPlanInactiveApprovalReceiptModel,
)
from apps.portfolio.transition_plan_owner_readers_composition import (
    build_django_transition_plan_owner_reader_runtime,
)


def read_locked_transition_order(
    *,
    plan_id: str,
    plan_version: int,
    ordinal: int,
    receipt_id: str,
    receipt_version: str,
    using: str,
    as_of: datetime,
) -> tuple[ExactActiveTransitionPlanOrderDefinition, ExactInactiveTransitionPlanApprovalReceipt]:
    """Lock the unique current plan and its immutable approval until the caller commits."""
    db = connections[using]
    if db.vendor != "postgresql" or not db.in_atomic_block:
        raise ValueError("portfolio_checkpoint_transaction_required")
    # The author can append a successor without updating the previously selected row.
    with db.cursor() as cursor:
        cursor.execute("""LOCK TABLE decision_portfolio_transition_plan,
                          portfolio_transition_inactive_approval_receipt,
                          portfolio_transition_inactive_approval_subject IN SHARE MODE NOWAIT""")
    plan_row = (
        PortfolioTransitionPlanModel._default_manager.using(using)
        .select_for_update()
        .filter(plan_id=plan_id, plan_version=plan_version)
        .values_list("pk", flat=True)
        .first()
    )
    receipt_row = (
        TransitionPlanInactiveApprovalReceiptModel._default_manager.using(using)
        .select_for_update()
        .filter(receipt_id=receipt_id, receipt_version=receipt_version)
        .values_list("pk", flat=True)
        .first()
    )
    if plan_row is None or receipt_row is None:
        raise ValueError("portfolio_checkpoint_plan_or_receipt_unavailable")
    runtime = build_django_transition_plan_owner_reader_runtime(using=using)
    return (
        runtime.plan_order_reader.execute(
            GetExactActiveTransitionPlanOrderQuery(
                plan_id=plan_id, plan_version=plan_version, order_ordinal=ordinal, as_of=as_of
            )
        ),
        runtime.inactive_receipt_reader.execute(
            GetExactInactiveTransitionPlanApprovalReceiptQuery(
                receipt_id=receipt_id, receipt_version=receipt_version, as_of=as_of
            )
        ),
    )
