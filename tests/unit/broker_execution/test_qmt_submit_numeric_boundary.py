"""Behavioral checks for QMT's numeric submission boundary."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from qmt_agent.qmt_adapter import XtQuantAdapter, encode_order_remark


class _FakeTrader:
    """Record QMT order submissions without contacting a broker."""

    def __init__(self, broker_order_id: object = 901) -> None:
        self.broker_order_id = broker_order_id
        self.calls: list[tuple[object, ...]] = []

    def order_stock(
        self,
        account: object,
        asset_code: object,
        side: object,
        quantity: object,
        price_type: object,
        limit_price: object,
        strategy_name: object,
        order_remark: object,
    ) -> object:
        """Capture the vendor arguments and return a configurable fake ID."""

        self.calls.append(
            (
                account,
                asset_code,
                side,
                quantity,
                price_type,
                limit_price,
                strategy_name,
                order_remark,
            )
        )
        return self.broker_order_id


class _FakeVendorCallbackBase:
    """Represent the callback base class exported by a local fake xtquant."""

    def on_disconnected(self) -> None:
        """Expose the callback method implemented by the adapter mixin."""

        raise NotImplementedError

    def on_stock_order(self, order: object) -> None:
        """Expose the callback method implemented by the adapter mixin."""

        raise NotImplementedError


class _FakeConnectionTrader:
    """Capture the connection and callback registration sequence."""

    def __init__(self, userdata_path: str, session_id: int) -> None:
        self.userdata_path = userdata_path
        self.session_id = session_id
        self.calls: list[str] = []
        self.callback: object | None = None

    def register_callback(self, callback: object) -> None:
        """Retain the callback instance registered by the adapter."""

        self.calls.append("register_callback")
        self.callback = callback

    def start(self) -> None:
        """Record that the local fake trader was started."""

        self.calls.append("start")

    def connect(self) -> int:
        """Report successful local fake connection."""

        self.calls.append("connect")
        return 0

    def subscribe(self, account: object) -> int:
        """Report successful local fake account subscription."""

        self.calls.append("subscribe")
        return 0


class _FakeStockAccount:
    """Represent the account wrapper exported by fake xtquant."""

    def __init__(self, account_id: str, account_type: str) -> None:
        self.account_id = account_id
        self.account_type = account_type


def _order(**overrides: Any) -> dict[str, Any]:
    """Build a minimal order payload consumed by the public adapter method."""

    return {
        "client_order_id": "00000000-0000-0000-0000-000000000001",
        "asset_code": "510300.SH",
        "side": "BUY",
        "quantity": "100",
        "limit_price": "3.90",
        **overrides,
    }


def _adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[XtQuantAdapter, _FakeTrader, object]:
    """Create an adapter wired only to in-memory fake QMT components."""

    constants = SimpleNamespace(STOCK_BUY=23, STOCK_SELL=24, FIX_PRICE=11)
    xtquant_module = ModuleType("xtquant")
    xtquant_module.xtconstant = constants
    monkeypatch.setitem(sys.modules, "xtquant", xtquant_module)

    adapter = XtQuantAdapter(
        userdata_path=Path("unused"),
        broker_account_id="fake-account",
    )
    trader = _FakeTrader()
    account = object()
    adapter.trader = trader
    adapter.account = account
    return adapter, trader, account


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("side", "HOLD", "side"),
        ("side", "buy", "side"),
        ("quantity", "0", "quantity"),
        ("quantity", "-1", "quantity"),
        ("quantity", "100.5", "quantity"),
        ("quantity", "NaN", "quantity"),
        ("quantity", "Infinity", "quantity"),
        ("quantity", "not-a-number", "quantity"),
        ("quantity", 100.0, "quantity"),
        ("quantity", True, "quantity"),
        ("limit_price", "0", "limit_price"),
        ("limit_price", "-1", "limit_price"),
        ("limit_price", "NaN", "limit_price"),
        ("limit_price", "Infinity", "limit_price"),
        ("limit_price", "not-a-number", "limit_price"),
        ("limit_price", "1e9999", "limit_price"),
        ("limit_price", "1e-9999", "limit_price"),
        ("limit_price", 3.9, "limit_price"),
        ("limit_price", "3.90000000000000001", "limit_price"),
    ],
)
def test_invalid_submission_is_rejected_before_vendor_call(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    adapter, trader, _account = _adapter(monkeypatch)

    with pytest.raises(ValueError, match=message):
        adapter.submit_order(_order(**{field: value}))

    assert trader.calls == []


@pytest.mark.parametrize(
    ("side", "vendor_side"),
    [("BUY", 23), ("SELL", 24)],
)
def test_valid_integer_stock_order_is_passed_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
    side: str,
    vendor_side: int,
) -> None:
    adapter, trader, account = _adapter(monkeypatch)
    order = _order(side=side, quantity="100.000", limit_price="3.90")

    result = adapter.submit_order(order)

    assert result.accepted is True
    assert result.broker_order_id == "901"
    assert trader.calls == [
        (
            account,
            "510300.SH",
            vendor_side,
            100,
            11,
            3.9,
            "AgomTradePro",
            encode_order_remark(order["client_order_id"]),
        )
    ]


def test_connect_lazily_builds_vendor_callback_subclass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xtquant_module = ModuleType("xtquant")
    xtquant_module.__path__ = []
    xtquant_module.xtconstant = SimpleNamespace(
        STOCK_BUY=23,
        STOCK_SELL=24,
        FIX_PRICE=11,
    )
    xttrader_module = ModuleType("xtquant.xttrader")
    xttrader_module.XtQuantTrader = _FakeConnectionTrader
    xttrader_module.XtQuantTraderCallback = _FakeVendorCallbackBase
    xttype_module = ModuleType("xtquant.xttype")
    xttype_module.StockAccount = _FakeStockAccount
    monkeypatch.setitem(sys.modules, "xtquant", xtquant_module)
    monkeypatch.setitem(sys.modules, "xtquant.xttrader", xttrader_module)
    monkeypatch.setitem(sys.modules, "xtquant.xttype", xttype_module)

    adapter = XtQuantAdapter(
        userdata_path=Path("unused"),
        broker_account_id="fake-account",
    )

    adapter.connect()

    assert isinstance(adapter.trader, _FakeConnectionTrader)
    assert adapter.trader.calls == [
        "register_callback",
        "start",
        "connect",
        "subscribe",
    ]
    assert isinstance(adapter.callback, _FakeVendorCallbackBase)
    assert adapter.trader.callback is adapter.callback
    assert isinstance(adapter.account, _FakeStockAccount)
    assert adapter.account.account_id == "fake-account"
    assert adapter.account.account_type == "STOCK"

    adapter._callback_dirty.clear()
    adapter.callback.on_stock_order(object())
    assert adapter._callback_dirty.is_set()
    adapter._callback_dirty.clear()
    adapter.callback.on_disconnected()
    assert adapter._callback_disconnected is True
    assert adapter._callback_dirty.is_set()
