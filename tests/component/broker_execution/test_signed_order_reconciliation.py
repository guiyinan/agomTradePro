"""Order-scoped source evidence and idempotency in snapshot reconciliation."""

from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentModel,
    BrokerExecutionAuditModel,
    BrokerFillModel,
    LiveOrderModel,
    ReconciliationRunModel,
)
from apps.broker_execution.infrastructure.repositories import DjangoBrokerExecutionRepository


@pytest.mark.django_db
def test_signed_order_reconciliation_requires_exact_snapshot_facts() -> None:
    owner = User.objects.create_user(username="snapshot-owner")
    agent = BrokerAgentModel.objects.create(user=owner, agent_id="snapshot-agent")
    BrokerAccountBindingModel.objects.create(
        user=owner, account_id=97, agent=agent, broker_account_ref="broker-97"
    )
    pin = {"order_id": str(uuid4()), "execution_scope_hash": "a" * 64}
    order = LiveOrderModel.objects.create(
        user=owner,
        agent=agent,
        account_id=97,
        client_order_id=pin["order_id"],
        authority_pin=pin,
        broker_order_id="B-7",
        asset_code="510300.SH",
        side="BUY",
        quantity="100",
        limit_price="3",
        status="PARTIALLY_FILLED",
        filled_quantity="50",
        version=7,
    )
    BrokerFillModel.objects.create(
        order=order,
        agent=agent,
        broker_account_ref="broker-97",
        broker_trade_id="T-7",
        quantity="50",
        price="2.99",
        amount="149.50",
        occurred_at=timezone.now(),
    )
    broker_order = {
        "client_order_id": pin["order_id"],
        "broker_order_id": "B-7",
        "asset_code": "510300.SH",
        "side": "BUY",
        "quantity": "100",
        "limit_price": "3.00",
        "status": "PARTIALLY_FILLED",
        "traded_quantity": "50",
    }
    trade = {
        "client_order_id": pin["order_id"],
        "broker_order_id": "B-7",
        "broker_trade_id": "T-7",
        "asset_code": "510300.SH",
        "quantity": "50",
        "price": "2.990",
    }
    snapshot = BrokerAccountSnapshotModel.objects.create(
        user=owner, agent=agent, account_id=97, captured_at=timezone.now()
    )
    repository = DjangoBrokerExecutionRepository()
    projection = {97: {"cash_available": "0", "total_asset": "0", "positions": []}}
    audits = BrokerExecutionAuditModel.objects.filter(
        resource_id=pin["order_id"], action="order_reconciled"
    )
    for orders, trades in [
        ([broker_order | {"client_order_id": str(uuid4())}], [trade]),
        ([broker_order | {"limit_price": "4"}], [trade]),
        ([broker_order, broker_order], [trade]),
        ([broker_order], [trade | {"price": "3.50"}]),
        ([broker_order], []),
        ([broker_order], [trade | {"broker_order_id": "wrong"}]),
    ]:
        snapshot.payload = {"orders": orders, "trades": trades}
        snapshot.save(update_fields=["payload"])
        assert (
            repository.generate_reconciliation_runs(account_projections=projection)["created_runs"]
            == 1
        )
        assert not audits.exists()
    snapshot.payload = {"orders": [broker_order], "trades": [trade]}
    snapshot.save(update_fields=["payload"])
    assert (
        repository.generate_reconciliation_runs(account_projections=projection)["created_runs"] == 1
    )
    assert (
        repository.generate_reconciliation_runs(account_projections=projection)["duplicate_runs"]
        == 1
    )
    record = audits.get()
    assert record.after["source_order"] == broker_order
    assert record.after["source_trades"] == [trade]
    assert record.after["authority_pin"] == pin and record.after["version"] == 7
    assert record.after["broker_source_at"] is None
    assert record.after["clock_source"] == "agent_snapshot"
    assert ReconciliationRunModel.objects.get(pk=record.after["run_id"]).status == "completed"
