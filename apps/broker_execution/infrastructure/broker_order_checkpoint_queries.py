"""Scoped reads of the order plan and its current checkpoint evidence."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import DatabaseError, OperationalError, router, transaction

from apps.broker_execution.application.evidence_gate import BROKER_ORDER_EVIDENCE_BLOCKER
from apps.broker_execution.application.use_case_errors import BrokerExecutionPermissionError
from apps.broker_execution.ash09_checkpoint_composition import (
    bounded_checkpoint_diagnostic,
    inspect_checkpoint_blockers,
    resolve_current_intent,
)

from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .models import BrokerAccountBindingModel, LiveOrderModel


def get_signed_order_plan(
    *, user_id: int, account_id: int, client_order_id: UUID
) -> dict[str, Any]:
    """Read the source order for risk evaluation before the locked creation check."""
    with transaction.atomic():
        intent = resolve_current_intent(
            client_order_id=client_order_id, account_id=account_id, using="default"
        )
        if intent.owner_user_id != user_id:
            raise BrokerExecutionPermissionError("Account access is not authorized")
        order = intent.snapshot
        return {
            "client_order_id": str(client_order_id),
            "account_id": account_id,
            "asset_code": order.asset_code,
            "side": order.side.value,
            "market": order.market,
            "quantity": str(order.quantity),
            "limit_price": str(order.limit_price),
            "expires_at": order.expires_at,
            "source_recommendation_ids": list(order.source_recommendation_ids),
            "source_signal_ids": list(order.source_signal_ids),
        }


def inspect_owned_order_checkpoint(
    repository: BrokerExecutionRepositoryMixinSupport,
    *,
    user_id: int,
    account_id: int,
    client_order_id: str,
) -> tuple[str, ...] | None:
    """Inspect only an authenticated owner of both the live order and its active binding."""
    using = router.db_for_write(LiveOrderModel)
    bindings = BrokerAccountBindingModel._default_manager.using(using).filter(
        user_id=user_id,
        account_id=account_id,
        is_active=True,
    )
    orders = LiveOrderModel._default_manager.using(using).filter(
        client_order_id=client_order_id,
        user_id=user_id,
        account_id=account_id,
    )
    try:
        with bounded_checkpoint_diagnostic(using=using):
            # A nonlocking read proves visibility before reporting even a generic busy state.
            if not orders.filter(agent_id__in=bindings.values("agent_id")).exists():
                return None
            try:
                with transaction.atomic(using=using):
                    order = orders.select_for_update(nowait=True, of=("self",)).first()
                    if (
                        order is None
                        or not bindings.select_for_update(nowait=True)
                        .filter(agent_id=order.agent_id)
                        .exists()
                    ):
                        return None
                    return inspect_checkpoint_blockers(
                        user_id=user_id,
                        client_order_id=order.client_order_id,
                        account_id=account_id,
                        order_payload=repository._order_payload(order),
                        using=using,
                    )
            except OperationalError:
                return (
                    BROKER_ORDER_EVIDENCE_BLOCKER,
                    "broker_checkpoint_temporarily_unavailable",
                )
    except DatabaseError:
        # Without an owned order and binding, no diagnostic facts may be disclosed.
        return None
