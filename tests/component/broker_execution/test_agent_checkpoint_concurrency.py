"""Native PostgreSQL serialization of subordinate Agent guards and immutable fills."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from queue import Queue
from typing import Any, TypeVar
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.utils import timezone

from apps.broker_execution.application import execution_price_guard
from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.domain.services import approval_digest_for_order
from apps.broker_execution.infrastructure import broker_repository_agent_runtime as runtime
from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentModel,
    BrokerFillModel,
    BrokerOrderEventModel,
    LiveOrderModel,
    OrderLeaseModel,
)
from apps.broker_execution.infrastructure.repositories import DjangoBrokerExecutionRepository
from tests.component.broker_execution.test_execution_contract_capabilities import (
    _mark_agent_online_for_submission,
    _ready_order_for_agent,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.unit.data_center.test_execution_quotes import _quote

pytestmark = pytest.mark.django_db(transaction=True)
_T = TypeVar("_T")


@pytest.fixture
def trading_pair() -> tuple[BrokerAgentModel, LiveOrderModel]:
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL transaction wait and rollback contract")
    owner = get_user_model().objects.bulk_create([get_user_model()(username=str(uuid4()))])[0]
    agent = BrokerAgentModel.objects.create(user=owner, agent_id=str(uuid4()), display_name="Test")
    now = timezone.now()
    _mark_agent_online_for_submission(agent, now=now, observed_at=now)
    BrokerAccountBindingModel.objects.create(
        user=owner,
        agent=agent,
        account_id=7,
        broker_account_ref="fixture",
        auto_execution_enabled=True,
        enforce_trading_session=False,
        allowed_symbols=["600000.SH"],
        max_single_order_amount=10000,
        daily_order_amount_limit=10000,
    )
    BrokerAccountSnapshotModel.objects.create(
        user=owner,
        agent=agent,
        account_id=7,
        captured_at=now,
        cash_available=10000,
    )
    return agent, _ready_order_for_agent(agent, now=now)


def _after_blocking_commit(writer: Callable[[], object], reader: Callable[[], _T]) -> _T:
    """Commit the first backend only after PG confirms it is blocking the second."""
    reader_pid: Queue[int] = Queue()

    def run_reader() -> _T:
        try:
            with connection.cursor() as cur:
                cur.execute("SET statement_timeout = '12s'")
                cur.execute("SELECT pg_backend_pid()")
                reader_pid.put(cur.fetchone()[0])
            return reader()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            writer()
            future = pool.submit(run_reader)
            pid = reader_pid.get(timeout=6)
            deadline = time.monotonic() + 6
            with connection.cursor() as cur:
                while True:
                    cur.execute("SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))", (pid,))
                    if cur.fetchone()[0]:
                        break
                    if future.done():
                        pytest.fail(f"Second backend finished without waiting: {future.result()!r}")
                    if time.monotonic() >= deadline:
                        pytest.fail("Second backend did not wait for the first transaction")
                    time.sleep(0.02)
        return future.result(timeout=12)


@pytest.mark.parametrize("stage", ["lease", "submitting"])
@pytest.mark.parametrize("change", ["disable", "stop", "disconnect", "stale"])
def test_subordinate_checkpoint_rechecks_committed_change_after_wait(
    trading_pair: tuple[BrokerAgentModel, LiveOrderModel],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    change: str,
) -> None:
    """The fixture bypasses Evidence only to exercise the secondary, locked denial."""
    agent, order = trading_pair
    repo = DjangoBrokerExecutionRepository()
    token = "fixture-token"
    now = timezone.now()
    quote = replace(
        _quote(),
        asset_code=order.asset_code,
        last=order.limit_price,
        snapshot_at=now,
        fetched_at=now,
        publication_as_of=now,
        published_at=now,
        queried_at=now,
        freshness_deadline=now + timedelta(seconds=60),
    )
    monkeypatch.setattr(
        execution_price_guard, "get_execution_quote", lambda *_args, **_kwargs: quote
    )
    order.refresh_from_db()
    order.approval_digest = approval_digest_for_order(repo._order_payload(order))
    order.save(update_fields=["approval_digest"])
    signed = Mock(valid_until=quote.freshness_deadline)
    signed.intent.sources.order.approval_digest = order.approval_digest
    monkeypatch.setattr(runtime, "verify_existing_order", lambda **kwargs: signed)
    if stage == "submitting":
        order.status = "LEASED"
        order.save(update_fields=["status"])
        now = timezone.now()
        OrderLeaseModel.objects.create(
            order=order,
            agent=agent,
            lease_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            leased_at=now,
            expires_at=now + timedelta(minutes=2),
        )
    monkeypatch.setattr(runtime, "broker_order_evidence_integrated", lambda: True)

    def checkpoint() -> dict[str, Any]:
        if stage == "lease":
            return repo.lease_agent_orders(
                agent_pk=agent.pk, allowed_account_ids=[7], limit=1, lease_seconds=30
            )
        return repo.acknowledge_submitting(
            agent_pk=agent.pk,
            allowed_account_ids=[7],
            client_order_id=str(order.client_order_id),
            lease_token=token,
        )

    # Same order, quote and lease, with the whole control advancement rolled back.
    with transaction.atomic():
        control = checkpoint()
        if stage == "lease":
            assert [row["client_order_id"] for row in control["orders"]] == [
                str(order.client_order_id)
            ]
        else:
            assert control["accepted"] and control["order"]["status"] == "SUBMITTING"
        transaction.set_rollback(True)

    def write_change() -> None:
        if change == "disable":
            BrokerAccountBindingModel.objects.filter(agent=agent).update(
                auto_execution_enabled=False
            )
        elif change == "stop":
            repo.set_kill_switch(
                user_id=agent.user_id,
                is_admin=False,
                account_id=7,
                active=True,
                reason="fixture",
                idempotency_key=str(uuid4()),
                request_digest="a" * 64,
            )
        elif change == "disconnect":
            BrokerAgentModel.objects.filter(pk=agent.pk).update(qmt_connected=False)
        else:
            stale = timezone.now() - timedelta(minutes=5)
            BrokerAgentModel.objects.filter(pk=agent.pk).update(
                health_snapshot={**agent.health_snapshot, "source_observed_at": stale.isoformat()}
            )

    def advance() -> str:
        try:
            result = checkpoint()
            if stage == "lease":
                assert result["total_count"] == 0 and result["orders"] == []
                return "not leased"
        except BrokerExecutionConflictError as exc:
            return str(exc)
        pytest.fail("Committed operational restriction allowed the order to advance")

    denied = _after_blocking_commit(write_change, advance)
    if stage == "lease" and change in {"disable", "stop"}:
        assert denied == "not leased"
    else:
        expected = {
            "disable": "disabled",
            "stop": "stopped",
            "disconnect": "not online",
            "stale": "stale",
        }
        assert expected[change] in denied
    order.refresh_from_db()
    assert (order.status, order.version) == (("LEASED" if stage == "submitting" else "READY"), 1)
    assert OrderLeaseModel.objects.filter(order=order).count() == int(stage == "submitting")


def test_competing_same_trade_on_two_orders_rolls_back_losing_event(
    trading_pair: tuple[BrokerAgentModel, LiveOrderModel],
) -> None:
    agent, first = trading_pair
    second = _ready_order_for_agent(agent, now=timezone.now())
    LiveOrderModel.objects.filter(pk__in=[first.pk, second.pk]).update(status="SUBMITTED")
    repo = DjangoBrokerExecutionRepository()
    observed = timezone.now().isoformat()

    def report(order: LiveOrderModel, event_id: str) -> dict[str, Any]:
        return repo.report_agent_events(
            agent_pk=agent.pk,
            allowed_account_ids=[7],
            events=[
                {
                    "client_order_id": str(order.client_order_id),
                    "event_id": event_id,
                    "event_type": "QMT_TRADE",
                    "status": "",
                    "occurred_at": observed,
                    "broker_order_id": str(order.pk),
                    "fill": {
                        "broker_account_ref": "fixture",
                        "broker_trade_id": "T1",
                        "quantity": "10",
                        "price": "9.90",
                        "occurred_at": observed,
                    },
                }
            ],
        )

    with pytest.raises(BrokerExecutionConflictError, match="already attached to another order"):
        _after_blocking_commit(lambda: report(first, "winner"), lambda: report(second, "loser"))
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.version, first.filled_quantity) == (2, Decimal("10"))
    assert (second.version, second.filled_quantity, second.broker_order_id) == (1, 0, "")
    assert list(BrokerOrderEventModel.objects.values_list("event_id", flat=True)) == ["winner"]
    assert list(BrokerFillModel.objects.values_list("order_id", flat=True)) == [first.pk]
