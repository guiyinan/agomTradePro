"""Apply broker order and fill reports to the locked order ledger."""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerAgentAuthenticationError,
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
)
from apps.broker_execution.domain.entities import TERMINAL_ORDER_STATUSES, LiveOrderStatus
from apps.broker_execution.domain.rules import is_prior_broker_status, validate_order_transition

from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .broker_trade_receipt import _TRADE_EVENTS, _read_trade_receipt, _receipt_clock, _receipt_time
from .models import (
    BrokerAccountBindingModel,
    BrokerFillModel,
    BrokerOrderEventModel,
    LiveOrderModel,
)

_ORDER_REPORTS = frozenset({"QMT_ORDER_STATUS", "FAKE_ORDER_STATUS", "AGENT_RECOVERY_QUERY"})
_BROKER_ORDER_STATES = frozenset(
    {
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCEL_PENDING",
        "CANCELED",
        "BROKER_REJECTED",
        "RECONCILIATION_REQUIRED",
    }
)
_TRADE_COMPATIBLE_STATES = frozenset(
    {
        "SUBMITTING",
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCEL_PENDING",
        "CANCELED",
        "RECONCILIATION_REQUIRED",
    }
)
_AGENT_OUTCOMES = {
    "DRY_RUN_VALIDATED": "",
    "ORDER_SUBMITTED": "SUBMITTED",
    "BROKER_REJECTED": "BROKER_REJECTED",
    "LOCAL_SUBMIT_VALIDATION_FAILED": "FAILED",
    "SERVER_ACK_OUTCOME_UNKNOWN": "RECONCILIATION_REQUIRED",
    "SUBMIT_OUTCOME_UNKNOWN": "RECONCILIATION_REQUIRED",
    "QMT_ORDER_IDENTITY_CONFLICT": "RECONCILIATION_REQUIRED",
    "QMT_ORDER_STATUS_UNKNOWN": "RECONCILIATION_REQUIRED",
}


def _event_target(
    order: LiveOrderModel, reported: str, event_type: str, broker_id: str
) -> tuple[str, bool]:
    """Return the resulting order state and any discrepancy requiring a stop."""

    if (
        event_type == "UNKNOWN"
        or (event_type in _AGENT_OUTCOMES and reported != _AGENT_OUTCOMES[event_type])
        or (event_type in _ORDER_REPORTS and reported not in _BROKER_ORDER_STATES)
        or (
            event_type in _TRADE_EVENTS
            and (reported or order.status not in _TRADE_COMPATIBLE_STATES)
        )
    ):
        reported = LiveOrderStatus.RECONCILIATION_REQUIRED.value
    if order.failure_code == "BROKER_OVERFILL":
        return LiveOrderStatus.RECONCILIATION_REQUIRED.value, True
    if not reported or reported == order.status:
        return reported, reported == LiveOrderStatus.RECONCILIATION_REQUIRED.value
    same_broker = bool(broker_id and order.broker_order_id == broker_id)
    if same_broker and is_prior_broker_status(order.status, reported):
        return order.status, False
    if (
        same_broker
        and order.status == "SUBMITTING"
        and event_type in _ORDER_REPORTS
        and (
            (reported == "PARTIALLY_FILLED" and 0 < order.filled_quantity < order.quantity)
            or (reported == "FILLED" and order.filled_quantity == order.quantity)
        )
    ):
        # A broker fill and aggregate report may both reach the server before the ACK.
        return reported, False
    try:
        validate_order_transition(order.status, reported)
    except ValueError:
        if order.status in TERMINAL_ORDER_STATUSES:
            return order.status, True
        return LiveOrderStatus.RECONCILIATION_REQUIRED.value, True
    return reported, reported == LiveOrderStatus.RECONCILIATION_REQUIRED.value


def apply_agent_event_batch(
    repository: BrokerExecutionRepositoryMixinSupport,
    *,
    agent_pk: int,
    allowed_account_ids: list[int],
    events: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply each receipt atomically and accumulate its committed alerts."""
    accepted = 0
    duplicates = 0
    reported_orders: set[int] = set()
    for item in events:
        event_id = str(item.get("event_id") or "").strip()
        client_order_id = str(item.get("client_order_id") or "").strip()
        if not event_id or not client_order_id:
            raise BrokerExecutionConflictError("event_id and client_order_id are required")
        committed_alert: dict[str, Any] | None = None
        with transaction.atomic():
            order = (
                LiveOrderModel._default_manager.select_for_update()
                .filter(client_order_id=client_order_id, agent_id=agent_pk)
                .first()
            )
            if order is None:
                raise BrokerExecutionNotFoundError("Event order does not exist")
            if order.account_id not in set(allowed_account_ids):
                raise BrokerAgentAuthenticationError("Event exceeds the credential account scope")
            reported_orders.add(order.pk)
            broker_id = str(item.get("broker_order_id") or "")
            reported = str(item.get("status") or "").upper()
            raw_type = str(item.get("event_type") or "UNKNOWN")
            event_type = (
                raw_type
                if (
                    raw_type in _TRADE_EVENTS
                    or raw_type in _ORDER_REPORTS
                    or raw_type in _AGENT_OUTCOMES
                )
                else "UNKNOWN"
            )
            if event_type != "UNKNOWN" and reported in {
                "DRAFT",
                "WAITING_APPROVAL",
                "READY",
                "LEASED",
                "SUBMITTING",
            }:
                raise BrokerExecutionConflictError(
                    "Broker report cannot advance a server authorization checkpoint"
                )
            event_payload = dict(item.get("payload") or {})
            received_at = timezone.now()
            occurred_at = _receipt_time(item.get("occurred_at"))
            clock, source = _receipt_clock(event_payload, occurred_at, received_at)
            if source is not None and event_type not in {"QMT_TRADE", "UNKNOWN"}:
                raise BrokerExecutionConflictError("This broker event has no broker source clock")
            event_payload.update(clock_source=clock, broker_source_at=source)
            fill = _read_trade_receipt(
                item.get("fill"), event_type, occurred_at, received_at, event_payload
            )
            identity: dict[str, object] = {
                "broker_order_id": broker_id,
                "event_type": raw_type,
                "reported_status": reported,
                "clock_source": clock,
                "broker_source_at": source,
            }
            if fill is not None:
                identity.update(
                    broker_trade_id=fill.trade_id,
                    quantity=str(fill.quantity.normalize()),
                    price=str(fill.price.normalize()),
                )
                if fill.account_ref is not None:
                    # Preserve account identity on replay without copying the vendor account into the timeline.
                    identity["broker_account_ref_hash"] = hashlib.sha256(
                        fill.account_ref.encode()
                    ).hexdigest()
            elif isinstance(item.get("fill"), dict):
                # An unknown sender's claim is retained for review and never posted as a fill.
                claimed = item["fill"]
                identity.update(
                    broker_trade_id=str(claimed.get("broker_trade_id") or ""),
                    quantity=str(claimed.get("quantity")),
                    price=str(claimed.get("price")),
                )
            target, needs_review = _event_target(order, reported, event_type, broker_id)
            event, created = BrokerOrderEventModel._default_manager.get_or_create(
                agent_id=agent_pk,
                event_id=event_id,
                defaults={
                    "order": order,
                    "event_type": event_type,
                    "status": target,
                    "payload": event_payload
                    | {
                        "reported_event_type": raw_type,
                        "reported_status": reported,
                        "order_version": order.version + 1,
                        "authority_pin": order.authority_pin,
                        "receipt_identity_v1": identity,
                    },
                    "occurred_at": occurred_at,
                },
            )
            if not created:
                previous = event.payload or {}
                stored_identity = previous.get("receipt_identity_v1")
                if stored_identity is None:
                    # Legacy rows did not store the original broker or fill selector.
                    matches = (
                        event.event_type == raw_type
                        and previous.get("reported_status", reported) == reported
                    )
                else:
                    matches = stored_identity == identity
                if event.order_id != order.pk or not matches:
                    raise BrokerExecutionConflictError(
                        "Broker event identity conflicts with its first report"
                    )
                duplicates += 1
                continue
            binding: BrokerAccountBindingModel | None = None
            if event_type.startswith(("QMT_", "FAKE_")):
                binding = (
                    BrokerAccountBindingModel._default_manager.select_for_update()
                    .filter(
                        agent_id=agent_pk,
                        user_id=order.user_id,
                        account_id=order.account_id,
                    )
                    .first()
                )
                if binding is None or (fill is not None and not binding.is_active):
                    raise BrokerAgentAuthenticationError("Event account is not bound to this Agent")
                # The fake adapter identifies its single vendor account as the literal "fake".
                if event_type.startswith("FAKE_") != (binding.broker_account_ref == "fake"):
                    raise BrokerExecutionConflictError("Broker account and report source disagree")
                if (
                    fill is not None
                    and fill.account_ref is not None
                    and fill.account_ref != binding.broker_account_ref
                ):
                    raise BrokerExecutionConflictError(
                        "Broker trade account differs from the order binding"
                    )
            if event_type == "UNKNOWN":
                logging.getLogger(
                    "apps.broker_execution.infrastructure.broker_repository_agent_runtime"
                ).warning("Unknown broker event type %r", raw_type)
            elif broker_id and order.broker_order_id and broker_id != order.broker_order_id:
                raise BrokerExecutionConflictError("Broker order identity changed")
            elif broker_id:
                order.broker_order_id = broker_id
            if target and target != order.status:
                order.status = target
            if (
                target
                in {
                    LiveOrderStatus.SUBMITTED.value,
                    LiveOrderStatus.PARTIALLY_FILLED.value,
                    LiveOrderStatus.FILLED.value,
                    LiveOrderStatus.CANCEL_PENDING.value,
                    LiveOrderStatus.CANCELED.value,
                }
                and not needs_review
                and order.submitted_at is None
            ):
                order.submitted_at = received_at
            if (
                target
                in {
                    LiveOrderStatus.BROKER_REJECTED.value,
                    LiveOrderStatus.FAILED.value,
                    LiveOrderStatus.RECONCILIATION_REQUIRED.value,
                }
                and order.failure_code != "BROKER_OVERFILL"
            ):
                order.failure_code = event_type
                order.failure_message = str(
                    event_payload.get("status_msg")
                    or event_payload.get("broker_message")
                    or event_payload.get("message")
                    or ""
                )[:2000]
            if fill is not None and binding is not None:
                persisted_fill, _created = BrokerFillModel._default_manager.get_or_create(
                    broker_account_ref=binding.broker_account_ref,
                    broker_trade_id=fill.trade_id,
                    defaults={
                        "order": order,
                        "agent_id": agent_pk,
                        "quantity": fill.quantity,
                        "price": fill.price,
                        "amount": fill.quantity * fill.price,
                        "occurred_at": fill.occurred_at,
                        "payload": fill.payload
                        | {
                            "event_id": event_id,
                            "order_version": order.version + 1,
                            "authority_pin": order.authority_pin,
                        },
                    },
                )
                if persisted_fill.order_id != order.pk:
                    raise BrokerExecutionConflictError(
                        "Broker trade is already attached to another order"
                    )
                if persisted_fill.quantity != fill.quantity or persisted_fill.price != fill.price:
                    raise BrokerExecutionConflictError(
                        "Broker trade identity has different fill economics"
                    )
                first_source = (persisted_fill.payload or {}).get("broker_source_at")
                if first_source is not None and (
                    source is None or _receipt_time(first_source) != _receipt_time(source)
                ):
                    raise BrokerExecutionConflictError(
                        "Broker trade identity has a different source time"
                    )
                totals = order.fills.aggregate(quantity=Sum("quantity"), amount=Sum("amount"))
                order.filled_quantity = totals["quantity"] or Decimal("0")
                if order.filled_quantity:
                    order.average_fill_price = (
                        totals["amount"] or Decimal("0")
                    ) / order.filled_quantity
                if order.filled_quantity > order.quantity:
                    target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                    order.status = target
                    order.failure_code = "BROKER_OVERFILL"
                    order.failure_message = (
                        "Broker cumulative fill quantity exceeds the approved order quantity"
                    )
            order.version += 1
            order.save()
            if needs_review or target == LiveOrderStatus.RECONCILIATION_REQUIRED.value:
                is_overfill = order.failure_code == "BROKER_OVERFILL"
                committed_alert = repository._upsert_operational_alert(
                    user_id=order.user_id,
                    account_id=order.account_id,
                    code=("P0_BROKER_OVERFILL" if is_overfill else "P0_ORDER_OUTCOME_UNKNOWN"),
                    severity="P0",
                    title=(
                        "券商累计成交超过批准数量，已自动停止新单"
                        if is_overfill
                        else "实盘订单结果未知，已自动停止新单"
                    ),
                    message=(
                        f"订单 {order.client_order_id} 出现超额成交，必须立即核验券商事实。"
                        if is_overfill
                        else f"订单 {order.client_order_id} 必须先查询券商事实并完成对账。"
                    ),
                    resource_key=str(order.client_order_id),
                    payload={"client_order_id": str(order.client_order_id)},
                    auto_stop=True,
                )
            accepted += 1
        if committed_alert is not None:
            alerts.append(committed_alert)
    return {
        "accepted_count": accepted,
        "duplicate_count": duplicates,
        "alerts": alerts,
        "order_states": [
            {
                "client_order_id": str(order_id),
                "status": status,
                "broker_order_id": broker_id,
                "version": version,
            }
            for order_id, status, broker_id, version in LiveOrderModel._default_manager.filter(
                pk__in=reported_orders, agent_id=agent_pk, account_id__in=allowed_account_ids
            )
            .order_by("pk")
            .values_list("client_order_id", "status", "broker_order_id", "version")
        ],
    }
