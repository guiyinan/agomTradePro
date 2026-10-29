from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.simulated_trading.application.order_history import (
    OrderFillHistoryPage,
    OrderHistoryFill,
    OrderHistoryOrder,
    OrderHistoryPage,
    ReadOrderHistoryUseCase,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation import OrderReservationStatus
from apps.simulated_trading.interface import order_history_views
from apps.simulated_trading.interface.order_history_views import (
    SimulatedOrderFillHistoryAPIView,
    SimulatedOrderHistoryAPIView,
)

_READ_AT = datetime(2026, 10, 29, 8, 15, tzinfo=UTC)


class _Reader:
    def __init__(self, *, order_page: OrderHistoryPage, fills_page: OrderFillHistoryPage) -> None:
        self.order_page = order_page
        self.fills_page = fills_page
        self.order_scope: tuple[int, int] | None = None
        self.fill_scope: tuple[int, int, int] | None = None

    def list_orders(self, *, account_id, user_id, limit, cursor, read_at):
        del limit, cursor
        self.order_scope = (account_id, user_id)
        assert read_at == _READ_AT
        return self.order_page

    def list_fills(self, *, account_id, user_id, order_id, limit, cursor, read_at):
        del limit, cursor
        self.fill_scope = (account_id, user_id, order_id)
        assert read_at == _READ_AT
        return self.fills_page


class _Clock:
    def now(self) -> datetime:
        return _READ_AT


def _order_page() -> OrderHistoryPage:
    return OrderHistoryPage(
        account_id=31,
        orders=(
            OrderHistoryOrder(
                order_id=78,
                asset_code="600000.SH",
                asset_name="浦发银行",
                side=SimulatedTradeSide.BUY,
                status=OrderReservationStatus.ACTIVE,
                quantity=Decimal("500.000000"),
                filled_quantity=Decimal("300.000000"),
                limit_price=Decimal("10.0000"),
                remaining_cash=Decimal("2005.00"),
                remaining_shares=Decimal("0.000000"),
                reserved_at=_READ_AT,
            ),
        ),
        has_more=False,
        next_cursor=None,
        membership_cutoff=_READ_AT,
        read_at=_READ_AT,
    )


def _fill_page() -> OrderFillHistoryPage:
    return OrderFillHistoryPage(
        account_id=31,
        order_id=78,
        fills=(
            OrderHistoryFill(
                receipt_id=901,
                trade_id=802,
                order_id=78,
                fill_sequence=1,
                asset_code="600000.SH",
                side=SimulatedTradeSide.BUY,
                quantity=Decimal("300.000000"),
                price=Decimal("9.9500"),
                occurred_at=_READ_AT,
                recorded_at=_READ_AT,
                observation_basis="daily_interval_end",
                verification_status="single_receipt_verified",
            ),
        ),
        has_more=False,
        next_cursor=None,
        membership_cutoff=_READ_AT,
        read_at=_READ_AT,
    )


@pytest.fixture
def authenticated_actor():
    return SimpleNamespace(id=42, pk=42, is_authenticated=True, is_active=True)


def test_order_history_http_contract_uses_authenticated_identity_and_whitelisted_fields(
    monkeypatch: pytest.MonkeyPatch,
    authenticated_actor: object,
) -> None:
    reader = _Reader(order_page=_order_page(), fills_page=_fill_page())
    use_case = ReadOrderHistoryUseCase(reader=reader, clock=_Clock())
    monkeypatch.setattr(order_history_views, "build_read_order_history_use_case", lambda: use_case)
    request = APIRequestFactory().get(
        reverse("simulated_trading_api:order-history", kwargs={"account_id": 31}),
        {"limit": "1"},
    )
    force_authenticate(request, user=authenticated_actor)

    response = SimulatedOrderHistoryAPIView.as_view()(request, account_id=31)
    response.render()

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert reader.order_scope == (31, 42)
    assert response.data["orders"][0] == {
        "order_id": 78,
        "asset_code": "600000.SH",
        "asset_name": "浦发银行",
        "side": "buy",
        "status": "active",
        "quantity": "500.000000",
        "filled_quantity": "300.000000",
        "limit_price": "10.0000",
        "remaining_cash": "2005.00",
        "remaining_shares": "0.000000",
        "reserved_at": _READ_AT.isoformat(),
    }
    assert "idempotency_key" not in response.data["orders"][0]
    assert "plan_snapshot" not in response.data["orders"][0]
    assert "intent_payload_hash" not in response.data["orders"][0]


def test_fill_history_http_contract_preserves_daily_basis_and_empty_scope_note(
    monkeypatch: pytest.MonkeyPatch,
    authenticated_actor: object,
) -> None:
    reader = _Reader(order_page=_order_page(), fills_page=_fill_page())
    use_case = ReadOrderHistoryUseCase(reader=reader, clock=_Clock())
    monkeypatch.setattr(order_history_views, "build_read_order_history_use_case", lambda: use_case)
    request = APIRequestFactory().get(
        reverse(
            "simulated_trading_api:order-fill-history",
            kwargs={"account_id": 31, "order_id": 78},
        )
    )
    force_authenticate(request, user=authenticated_actor)

    response = SimulatedOrderFillHistoryAPIView.as_view()(request, account_id=31, order_id=78)
    response.render()

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert reader.fill_scope == (31, 42, 78)
    fill = response.data["fills"][0]
    assert fill["receipt_id"] == 901
    assert fill["quantity"] == "300.000000"
    assert fill["price"] == "9.9500"
    assert fill["observation_basis"] == "daily_interval_end"
    assert fill["verification_status"] == "single_receipt_verified"
    assert response.data["receipt_scope_note"] == (
        "本页仅列已留存且完成单条核对的成交回执；空列表不能证明从未成交。"
    )
    assert "source_event_id" not in fill
    assert "receipt_hash" not in fill


def test_api_rejects_caller_identity_or_cutoff_query_fields_before_read(
    monkeypatch: pytest.MonkeyPatch,
    authenticated_actor: object,
) -> None:
    builder = Mock(side_effect=AssertionError("invalid query reached the reader"))
    monkeypatch.setattr(order_history_views, "build_read_order_history_use_case", builder)
    request = APIRequestFactory().get(
        "/api/simulated-trading/accounts/31/orders/",
        {"user_id": "999", "membership_cutoff": "2099-01-01T00:00:00Z"},
    )
    force_authenticate(request, user=authenticated_actor)

    response = SimulatedOrderHistoryAPIView.as_view()(request, account_id=31)
    response.render()

    assert response.status_code == 400
    assert response["Content-Type"] == "application/json"
    assert response.data["code"] == "ORDER_HISTORY_INPUT_INVALID"
    builder.assert_not_called()


def test_api_rejects_an_inactive_request_actor_before_usecase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = Mock(side_effect=AssertionError("inactive actor reached the reader"))
    monkeypatch.setattr(order_history_views, "build_read_order_history_use_case", builder)
    request = APIRequestFactory().get("/api/simulated-trading/accounts/31/orders/")
    force_authenticate(
        request,
        user=SimpleNamespace(id=42, pk=42, is_authenticated=True, is_active=False),
    )

    response = SimulatedOrderHistoryAPIView.as_view()(request, account_id=31)
    response.render()

    assert response.status_code == 403
    assert response.data["code"] == "ACTOR_INACTIVE"
    builder.assert_not_called()
