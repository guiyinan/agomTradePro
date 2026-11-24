"""Exercise the signed machine's order, fill and snapshot endpoints after authorization."""

from decimal import Decimal
from uuid import uuid4

from django.utils import timezone

from apps.broker_execution.application.tasks import generate_broker_reconciliation_runs
from apps.broker_execution.infrastructure.models import (
    BrokerAccountSnapshotModel,
    BrokerExecutionAuditModel,
    ReconciliationRunModel,
)


def assert_signed_order_reconciliation(*, order, machine):
    """Reconcile the signed order at the normal task entry while the REAL ledger stays under review."""
    client_id = str(order.client_order_id)
    broker_id, trade_id = f"B-{uuid4().hex}", f"T-{uuid4().hex}"
    starting = BrokerAccountSnapshotModel.objects.filter(
        account_id=order.account_id,
        agent_id=order.agent_id,
        user_id=order.user_id,
        captured_at__lte=timezone.now(),
    ).latest("captured_at")
    broker_clock = {"clock_source": "agent_observed", "broker_source_at": None}
    event = {
        "client_order_id": client_id,
        "broker_order_id": broker_id,
        "occurred_at": timezone.now().isoformat(),
        "payload": broker_clock,
    }
    unit_price, quantity = order.limit_price, order.quantity
    assert order.side == "BUY" and unit_price and quantity > 0
    events = [
        event
        | {"event_id": "signed-broker-ack", "event_type": "ORDER_SUBMITTED", "status": "SUBMITTED"},
        event
        | {
            "event_id": "signed-trade",
            "event_type": "QMT_TRADE",
            "fill": {
                "broker_trade_id": trade_id,
                "quantity": str(quantity),
                "price": str(unit_price),
                "occurred_at": event["occurred_at"],
            },
        },
        event | {"event_id": "signed-filled", "event_type": "QMT_ORDER_STATUS", "status": "FILLED"},
    ]
    machine("events", {"events": events})
    order.refresh_from_db()
    assert order.status == "FILLED" and order.filled_quantity == quantity
    for row in order.broker_events.all():
        assert row.payload["authority_pin"] == order.authority_pin
        assert (
            row.payload["broker_source_at"] is None
            and row.payload["clock_source"] == "agent_observed"
        )
    fill = order.fills.get()
    assert (
        fill.payload["authority_pin"] == order.authority_pin
        and fill.payload["event_id"] == "signed-trade"
    )

    keys = {
        "client_order_id": client_id,
        "broker_order_id": broker_id,
        "asset_code": order.asset_code,
    }
    source_order = keys | {
        "side": order.side,
        "quantity": str(quantity),
        "limit_price": str(unit_price),
        "status": "FILLED",
        "traded_quantity": str(quantity),
    }
    source_trade = keys | {
        "broker_trade_id": trade_id,
        "price": str(unit_price),
        "quantity": str(quantity),
    }
    snapshot = {
        "account_id": order.account_id,
        "captured_at": timezone.now().isoformat(),
        "cash_available": str(
            (starting.cash_available - quantity * unit_price).quantize(Decimal("0.01"))
        ),
        "total_asset": str(starting.total_asset),
        "positions": [
            {"asset_code": order.asset_code, "quantity": str(quantity), "available_quantity": "0"}
        ],
        "orders": [source_order],
    }
    # A broker correction may reuse a capture timestamp. Retain each distinct comparison.
    facts = BrokerExecutionAuditModel.objects.filter(
        resource_type="live_order", resource_id=client_id, action="order_reconciled"
    )
    for trades in ([], [source_trade | {"price": str(unit_price + Decimal("0.01"))}]):
        machine("snapshots", snapshot | {"trades": trades})
        generate_broker_reconciliation_runs()
        assert not facts.exists()
    machine("snapshots", snapshot | {"trades": [source_trade]})
    generate_broker_reconciliation_runs()
    generate_broker_reconciliation_runs()
    proof = facts.get().after
    assert proof["scope"] == "order_and_fills" and proof["authority_pin"] == order.authority_pin
    assert proof["version"] == order.version and proof["broker_source_at"] is None
    assert proof["source_order"]["broker_order_id"] == broker_id
    assert [row["broker_trade_id"] for row in proof["source_trades"]] == [trade_id]
    run = ReconciliationRunModel.objects.get(pk=proof["run_id"])
    assert run.status == proof["run_status"] == "review_required" and run.cash_difference_count > 0
