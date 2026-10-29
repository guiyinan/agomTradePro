from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.order_history import (
    OrderFillHistoryPage,
    OrderHistoryPage,
    ReadOrderHistoryUseCase,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide

_READ_AT = datetime(2026, 10, 29, 8, 15, tzinfo=UTC)


@dataclass(frozen=True)
class _OrderPageCall:
    account_id: int
    user_id: int
    limit: int
    cursor: str | None
    read_at: datetime


@dataclass(frozen=True)
class _FillPageCall:
    account_id: int
    user_id: int
    order_id: int
    limit: int
    cursor: str | None
    read_at: datetime


class _Clock:
    def now(self) -> datetime:
        return _READ_AT


class _Reader:
    def __init__(self) -> None:
        self.order_calls: list[_OrderPageCall] = []
        self.fill_calls: list[_FillPageCall] = []

    def list_orders(
        self,
        *,
        account_id: int,
        user_id: int,
        limit: int,
        cursor: str | None,
        read_at: datetime,
    ) -> OrderHistoryPage:
        self.order_calls.append(_OrderPageCall(account_id, user_id, limit, cursor, read_at))
        return OrderHistoryPage(
            account_id=account_id,
            orders=(),
            has_more=False,
            next_cursor=None,
            membership_cutoff=read_at,
            read_at=read_at,
        )

    def list_fills(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        limit: int,
        cursor: str | None,
        read_at: datetime,
    ) -> OrderFillHistoryPage:
        self.fill_calls.append(_FillPageCall(account_id, user_id, order_id, limit, cursor, read_at))
        return OrderFillHistoryPage(
            account_id=account_id,
            order_id=order_id,
            fills=(),
            has_more=False,
            next_cursor=None,
            membership_cutoff=read_at,
            read_at=read_at,
        )


def test_orders_usecase_uses_authenticated_owner_scope_and_server_clock() -> None:
    reader = _Reader()
    use_case = ReadOrderHistoryUseCase(reader=reader, clock=_Clock())

    page = use_case.read_orders(account_id=31, user_id=42, limit=17, cursor=None)

    assert page.account_id == 31
    assert page.orders == ()
    assert page.membership_cutoff == _READ_AT
    assert page.read_at == _READ_AT
    assert reader.order_calls == [_OrderPageCall(31, 42, 17, None, _READ_AT)]


def test_fills_usecase_keeps_order_scope_and_server_clock() -> None:
    reader = _Reader()
    use_case = ReadOrderHistoryUseCase(reader=reader, clock=_Clock())

    page = use_case.read_fills(
        account_id=31,
        user_id=42,
        order_id=99,
        limit=9,
        cursor="opaque-cursor",
    )

    assert page.account_id == 31
    assert page.order_id == 99
    assert page.fills == ()
    assert reader.fill_calls == [_FillPageCall(31, 42, 99, 9, "opaque-cursor", _READ_AT)]


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("read_orders", {"account_id": 0, "user_id": 42, "limit": 50, "cursor": None}),
        ("read_orders", {"account_id": 31, "user_id": 0, "limit": 50, "cursor": None}),
        ("read_orders", {"account_id": 31, "user_id": 42, "limit": 0, "cursor": None}),
        ("read_orders", {"account_id": 31, "user_id": 42, "limit": 101, "cursor": None}),
        ("read_orders", {"account_id": 31, "user_id": 42, "limit": True, "cursor": None}),
        (
            "read_fills",
            {
                "account_id": 31,
                "user_id": 42,
                "order_id": 0,
                "limit": 50,
                "cursor": None,
            },
        ),
        (
            "read_fills",
            {
                "account_id": 31,
                "user_id": 42,
                "order_id": 99,
                "limit": 50,
                "cursor": " ",
            },
        ),
    ],
)
def test_usecase_rejects_invalid_scope_and_paging_before_repository(
    method: str,
    kwargs: dict[str, object],
) -> None:
    reader = _Reader()
    use_case = ReadOrderHistoryUseCase(reader=reader, clock=_Clock())

    with pytest.raises(SimulatedTradeExecutionInputError):
        getattr(use_case, method)(**kwargs)

    assert reader.order_calls == []
    assert reader.fill_calls == []


def test_page_rejects_future_or_naive_member_cutoff() -> None:
    with pytest.raises(ValueError):
        OrderHistoryPage(
            account_id=31,
            orders=(),
            has_more=False,
            next_cursor=None,
            membership_cutoff=datetime(2026, 10, 29, 8, 16, tzinfo=UTC),
            read_at=_READ_AT,
        )

    with pytest.raises(ValueError):
        OrderFillHistoryPage(
            account_id=31,
            order_id=99,
            fills=(),
            has_more=False,
            next_cursor=None,
            membership_cutoff=datetime(2026, 10, 29, 8, 15),
            read_at=_READ_AT,
        )


def test_fill_row_requires_exact_decimal_fields_and_explicit_basis() -> None:
    from apps.simulated_trading.application.order_history import OrderHistoryFill

    with pytest.raises(ValueError):
        OrderHistoryFill(
            receipt_id=1,
            trade_id=2,
            order_id=3,
            fill_sequence=1,
            asset_code="600000.SH",
            side=SimulatedTradeSide.BUY,
            quantity=Decimal("10"),
            price=10.0,  # type: ignore[arg-type]
            occurred_at=_READ_AT,
            recorded_at=_READ_AT,
            observation_basis="daily_interval_end",
            verification_status="single_receipt_verified",
        )
