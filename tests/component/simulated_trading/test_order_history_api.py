"""Real owner API checks for read-only order and receipt history."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, models
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedTradeModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _Clock,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_read_compat import (
    _persist_v4_fill,
)
from tests.component.simulated_trading.test_order_reservation_fill_read_compat import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_fill_read_compat import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _persist_two_active_fills,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _create_reservation as _create_fill_reservation,
)
from tests.component.simulated_trading.test_order_reservation_repository import _Harness
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _authenticated_client(user: object) -> APIClient:
    """Return a DRF client authenticated as the exact supplied database actor."""

    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _api_write_queries(queries: list[dict[str, object]]) -> list[str]:
    """Return SQL statements that would mutate retained history or ledger rows."""

    return [
        str(query["sql"])
        for query in queries
        if re.match(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", str(query["sql"]), re.I)
    ]


@dataclass(frozen=True)
class _OrderHistoryOwnerReceiptFixture:
    """Reusable real owner/order/Trade/receipt chain for read-only API checks."""

    harness: _Harness
    order: SimulatedOrderReservationModel
    trade: SimulatedTradeModel
    receipt: SimulatedOrderFillReceiptModel
    owner: object


@pytest.fixture
def order_history_owner_with_receipt(
    reservation_harness,
    persisted_receipt_schema,
) -> _OrderHistoryOwnerReceiptFixture:
    """Build one ordinary owner and a real Reservation/Trade/receipt chain.

    The source evidence is the existing synthetic component fixture. This is
    suitable for API/history wiring tests and does not represent live QMT
    qualification.
    """

    del persisted_receipt_schema
    harness = cast(_Harness, reservation_harness)
    trade, receipt = _persist_v4_fill(
        harness,
        side=SimulatedTradeSide.BUY,
        first_buy=True,
    )
    order = SimulatedOrderReservationModel._base_manager.get(pk=receipt.reservation_id)
    owner = get_user_model()._default_manager.get(pk=harness.user_id)
    return _OrderHistoryOwnerReceiptFixture(
        harness=harness,
        order=order,
        trade=trade,
        receipt=receipt,
        owner=owner,
    )


def test_owner_can_list_terminal_orders_from_inactive_account_without_writes(
    reservation_harness,
) -> None:
    harness = reservation_harness
    order = _create_fill_reservation(harness, key="history-terminal-order")
    harness.repository.cancel_order(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        idempotency_key=order.idempotency_key,
        clock=_Clock(AS_OF),
    )
    order.refresh_from_db()
    harness.account.is_active = False
    harness.account.save(update_fields=["is_active"])
    user = get_user_model()._default_manager.get(pk=harness.user_id)
    client = _authenticated_client(user)

    with CaptureQueriesContext(connection) as queries:
        response = client.get(f"/api/simulated-trading/accounts/{harness.account.pk}/orders/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.data["account_id"] == harness.account.pk
    assert len(response.data["orders"]) == 1
    row = response.data["orders"][0]
    assert row["order_id"] == order.pk
    assert row["status"] == "cancelled"
    assert row["quantity"] == str(order.quantity)
    assert row["filled_quantity"] == str(order.filled_quantity)
    assert row["remaining_cash"] == str(
        order.cash_reserved - order.cash_consumed - order.cash_released
    )
    assert "idempotency_key" not in row
    assert "plan_snapshot" not in row
    assert _api_write_queries(queries.captured_queries) == []


def test_owner_reads_exact_terminal_receipt_without_source_reads_or_ledger_writes(
    order_history_owner_with_receipt: _OrderHistoryOwnerReceiptFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = order_history_owner_with_receipt
    harness = fixture.harness
    order = fixture.order
    trade = fixture.trade
    receipt = fixture.receipt
    assert trade.pk == receipt.trade_id
    harness.repository.cancel_order(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        idempotency_key=order.idempotency_key,
        clock=_Clock(AS_OF),
    )
    order.refresh_from_db()
    assert order.status == SimulatedOrderReservationModel.STATUS_CANCELLED
    client = _authenticated_client(fixture.owner)

    def _unexpected_source_read(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("receipt history attempted matcher source discovery")

    monkeypatch.setattr(DjangoLocalDailyMatchEventReader, "read_event", _unexpected_source_read)
    monkeypatch.setattr(DjangoLocalDailyMatchEventReader, "discover", _unexpected_source_read)
    reservation_before = tuple(
        SimulatedOrderReservationModel._base_manager.filter(pk=order.pk)
        .values_list("status", "filled_quantity", "cash_consumed", "cash_released")
        .get()
    )
    receipt_before = tuple(
        SimulatedOrderFillReceiptModel._base_manager.filter(pk=receipt.pk)
        .values_list("receipt_hash", "created_at", "source_event_payload_hash")
        .get()
    )
    trade_count_before = SimulatedTradeModel._base_manager.count()

    with CaptureQueriesContext(connection) as queries:
        response = client.get(
            f"/api/simulated-trading/accounts/{harness.account.pk}/orders/{order.pk}/fills/"
        )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.data["account_id"] == harness.account.pk
    assert response.data["order_id"] == order.pk
    assert len(response.data["fills"]) == 1
    fill = response.data["fills"][0]
    assert fill["receipt_id"] == receipt.pk
    assert fill["trade_id"] == trade.pk
    assert fill["order_id"] == order.pk
    assert fill["fill_sequence"] == receipt.fill_sequence
    assert fill["asset_code"] == order.asset_code
    assert fill["side"] == "buy"
    assert fill["quantity"] == str(trade.quantity)
    assert fill["price"] == str(trade.price)
    assert datetime.fromisoformat(fill["occurred_at"]) == datetime.fromisoformat(
        receipt.source_event_payload["occurred_at"]
    )
    assert fill["recorded_at"] == receipt.created_at.isoformat()
    assert fill["observation_basis"] == "legacy_source_observed"
    assert fill["verification_status"] == "single_receipt_verified"
    assert "source_event_id" not in fill
    assert "receipt_hash" not in fill
    assert "source_observed_at" not in fill
    assert response.data["receipt_scope_note"] == (
        "本页仅列已留存且完成单条核对的成交回执；空列表不能证明从未成交。"
    )
    assert _api_write_queries(queries.captured_queries) == []
    assert (
        tuple(
            SimulatedOrderReservationModel._base_manager.filter(pk=order.pk)
            .values_list("status", "filled_quantity", "cash_consumed", "cash_released")
            .get()
        )
        == reservation_before
    )
    assert (
        tuple(
            SimulatedOrderFillReceiptModel._base_manager.filter(pk=receipt.pk)
            .values_list("receipt_hash", "created_at", "source_event_payload_hash")
            .get()
        )
        == receipt_before
    )
    assert SimulatedTradeModel._base_manager.count() == trade_count_before


def test_owner_can_page_both_real_receipts_from_an_active_two_fill_order(
    reservation_harness,
    persisted_receipt_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del persisted_receipt_schema
    harness = cast(_Harness, reservation_harness)
    state = _persist_two_active_fills(harness)
    order = state.rows.reservation
    first_receipt = SimulatedOrderFillReceiptModel._base_manager.get(
        reservation_id=order.pk,
        fill_sequence=1,
    )
    second_receipt = SimulatedOrderFillReceiptModel._base_manager.get(
        reservation_id=order.pk,
        fill_sequence=2,
    )
    assert first_receipt.trade_id == state.first_result.trade_id
    assert second_receipt.trade_id == state.second_result.trade_id
    owner = get_user_model()._default_manager.get(pk=harness.user_id)
    client = _authenticated_client(owner)

    def _unexpected_source_read(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("receipt pagination attempted matcher source discovery")

    monkeypatch.setattr(DjangoLocalDailyMatchEventReader, "read_event", _unexpected_source_read)
    monkeypatch.setattr(DjangoLocalDailyMatchEventReader, "discover", _unexpected_source_read)
    first = client.get(
        f"/api/simulated-trading/accounts/{harness.account.pk}/orders/{order.pk}/fills/",
        {"limit": 1},
    )
    assert first.status_code == 200
    assert first.data["has_more"] is True
    assert len(first.data["fills"]) == 1
    assert first.data["fills"][0]["receipt_id"] == first_receipt.pk
    assert first.data["fills"][0]["trade_id"] == state.first_result.trade_id
    assert first.data["fills"][0]["fill_sequence"] == 1
    assert first.data["fills"][0]["observation_basis"] == "legacy_source_observed"

    second = client.get(
        f"/api/simulated-trading/accounts/{harness.account.pk}/orders/{order.pk}/fills/",
        {"limit": 1, "cursor": first.data["next_cursor"]},
    )

    assert second.status_code == 200
    assert second.data["membership_cutoff"] == first.data["membership_cutoff"]
    assert second.data["has_more"] is False
    assert len(second.data["fills"]) == 1
    assert second.data["fills"][0]["receipt_id"] == second_receipt.pk
    assert second.data["fills"][0]["trade_id"] == state.second_result.trade_id
    assert second.data["fills"][0]["fill_sequence"] == 2
    assert second.data["fills"][0]["observation_basis"] == "legacy_source_observed"


def test_empty_receipt_page_does_not_claim_no_fill_or_release_hold(reservation_harness) -> None:
    harness = reservation_harness
    order = _create_fill_reservation(harness, key="history-no-receipt")
    before = (
        order.status,
        order.filled_quantity,
        order.cash_consumed,
        order.cash_released,
    )
    user = get_user_model()._default_manager.get(pk=harness.user_id)
    response = _authenticated_client(user).get(
        f"/api/simulated-trading/accounts/{harness.account.pk}/orders/{order.pk}/fills/"
    )

    order.refresh_from_db()
    assert response.status_code == 200
    assert response.data["fills"] == []
    assert "空列表不能证明从未成交" in response.data["receipt_scope_note"]
    assert (order.status, order.filled_quantity, order.cash_consumed, order.cash_released) == before


def test_foreign_superuser_cannot_read_an_owners_order_history(reservation_harness) -> None:
    harness = reservation_harness
    order = _create_fill_reservation(harness, key="history-private-order")
    superuser = get_user_model()._default_manager.create_user(
        username="history-foreign-superuser",
        password="test-password",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )

    response = _authenticated_client(superuser).get(
        f"/api/simulated-trading/accounts/{harness.account.pk}/orders/"
    )

    assert response.status_code == 404
    assert response.data["code"] == "ORDER_HISTORY_NOT_FOUND"
    assert order.pk not in [row["order_id"] for row in response.data.get("orders", [])]


@pytest.mark.parametrize(
    ("is_staff", "is_superuser"),
    [(True, False), (True, True)],
)
def test_staff_and_superuser_do_not_bypass_current_owner_scope(
    reservation_harness,
    is_staff: bool,
    is_superuser: bool,
) -> None:
    harness = reservation_harness
    _create_fill_reservation(harness, key=f"history-staff-{is_superuser}")
    staff = get_user_model()._default_manager.create_user(
        username=f"history-staff-{is_superuser}",
        password="test-password",
        is_staff=is_staff,
        is_superuser=is_superuser,
        is_active=True,
    )

    response = _authenticated_client(staff).get(
        f"/api/simulated-trading/accounts/{harness.account.pk}/orders/"
    )

    assert response.status_code == 404
    assert response.data["code"] == "ORDER_HISTORY_NOT_FOUND"


def test_database_inactive_actor_is_rejected_before_history_read(
    order_history_owner_with_receipt: _OrderHistoryOwnerReceiptFixture,
) -> None:
    fixture = order_history_owner_with_receipt
    fixture.owner.is_active = False
    fixture.owner.save(update_fields=["is_active"])

    response = _authenticated_client(fixture.owner).get(
        f"/api/simulated-trading/accounts/{fixture.harness.account.pk}/orders/"
    )

    assert response.status_code == 403
    assert response.data["code"] == "ACTOR_INACTIVE"


@pytest.mark.parametrize("endpoint", ["orders", "fills"])
def test_owner_history_rejects_query_supplied_user_id(
    reservation_harness,
    endpoint: str,
) -> None:
    harness = reservation_harness
    order = _create_fill_reservation(harness, key=f"history-forged-owner-{endpoint}")
    user = get_user_model()._default_manager.get(pk=harness.user_id)
    path = f"/api/simulated-trading/accounts/{harness.account.pk}/orders/"
    if endpoint == "fills":
        path += f"{order.pk}/fills/"

    response = _authenticated_client(user).get(path, {"user_id": "999999"})

    assert response.status_code == 400
    assert response.data["code"] == "ORDER_HISTORY_INPUT_INVALID"


def test_cursor_keeps_membership_but_returns_current_order_state(
    reservation_harness,
) -> None:
    harness = reservation_harness
    first_order = _create_fill_reservation(harness, key="history-current-first")
    second_order = _create_fill_reservation(harness, key="history-current-second")
    user = get_user_model()._default_manager.get(pk=harness.user_id)
    client = _authenticated_client(user)
    first_page = client.get(
        f"/api/simulated-trading/accounts/{harness.account.pk}/orders/",
        {"limit": 1},
    )
    assert first_page.status_code == 200
    assert first_page.data["has_more"] is True
    assert first_page.data["orders"][0]["order_id"] == first_order.pk
    cutoff = datetime.fromisoformat(first_page.data["membership_cutoff"])

    harness.repository.cancel_order(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        idempotency_key=second_order.idempotency_key,
        clock=_Clock(AS_OF),
    )
    third_order = _create_fill_reservation(harness, key="history-current-third")
    assert third_order.created_at > cutoff

    second_page = client.get(
        f"/api/simulated-trading/accounts/{harness.account.pk}/orders/",
        {"limit": 1, "cursor": first_page.data["next_cursor"]},
    )

    assert second_page.status_code == 200
    assert second_page.data["membership_cutoff"] == first_page.data["membership_cutoff"]
    assert [row["order_id"] for row in second_page.data["orders"]] == [second_order.pk]
    assert second_page.data["orders"][0]["status"] == "cancelled"
    assert third_order.pk not in [row["order_id"] for row in second_page.data["orders"]]


def test_orders_cursor_pages_are_scoped_and_keep_membership_cutoff(reservation_harness) -> None:
    harness = reservation_harness
    orders = tuple(
        _create_fill_reservation(harness, key=f"history-page-{index}") for index in range(3)
    )
    user = get_user_model()._default_manager.get(pk=harness.user_id)
    client = _authenticated_client(user)

    first = client.get(
        f"/api/simulated-trading/accounts/{harness.account.pk}/orders/",
        {"limit": 2},
    )
    assert first.status_code == 200
    assert first.data["has_more"] is True
    assert first.data["next_cursor"]
    cutoff = first.data["membership_cutoff"]
    first_ids = [row["order_id"] for row in first.data["orders"]]

    second = client.get(
        f"/api/simulated-trading/accounts/{harness.account.pk}/orders/",
        {"limit": 2, "cursor": first.data["next_cursor"]},
    )

    assert second.status_code == 200
    assert second.data["membership_cutoff"] == cutoff
    second_ids = [row["order_id"] for row in second.data["orders"]]
    assert set(first_ids + second_ids) == {order.pk for order in orders}
    assert len(first_ids + second_ids) == 3


def test_corrupt_reservation_snapshot_blocks_owner_history_without_disclosure(
    reservation_harness,
) -> None:
    harness = reservation_harness
    order = _create_fill_reservation(harness, key="history-corrupt-order")
    query = SimulatedOrderReservationModel._base_manager.filter(pk=order.pk)
    models.QuerySet.update(query, plan_snapshot_hash="f" * 64)
    user = get_user_model()._default_manager.get(pk=harness.user_id)

    response = _authenticated_client(user).get(
        f"/api/simulated-trading/accounts/{harness.account.pk}/orders/"
    )

    assert response.status_code == 409
    assert response.data["code"] == "ORDER_RESERVATION_SNAPSHOT_INVALID"
    assert "plan_snapshot" not in response.data


def test_corrupt_single_receipt_blocks_without_claiming_empty_history(
    order_history_owner_with_receipt: _OrderHistoryOwnerReceiptFixture,
) -> None:
    fixture = order_history_owner_with_receipt
    harness = fixture.harness
    order = fixture.order
    receipt = fixture.receipt
    query = SimulatedOrderFillReceiptModel._base_manager.filter(pk=receipt.pk)
    models.QuerySet.update(query, receipt_hash="0" * 64)
    before = tuple(
        SimulatedOrderReservationModel._base_manager.filter(pk=order.pk)
        .values_list("status", "filled_quantity", "cash_consumed", "cash_released")
        .get()
    )
    trade_count_before = SimulatedTradeModel._base_manager.count()

    with CaptureQueriesContext(connection) as queries:
        response = _authenticated_client(fixture.owner).get(
            f"/api/simulated-trading/accounts/{harness.account.pk}/orders/{order.pk}/fills/"
        )

    assert response.status_code == 409
    assert response.data["code"] in {
        "ORDER_HISTORY_RECEIPT_INVALID",
        "SIMULATED_FILL_RECEIPT_INVALID",
    }
    assert response.data.get("fills") is None
    assert _api_write_queries(queries.captured_queries) == []
    assert (
        tuple(
            SimulatedOrderReservationModel._base_manager.filter(pk=order.pk)
            .values_list("status", "filled_quantity", "cash_consumed", "cash_released")
            .get()
        )
        == before
    )
    assert SimulatedTradeModel._base_manager.count() == trade_count_before
