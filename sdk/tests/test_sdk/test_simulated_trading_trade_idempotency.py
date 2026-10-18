"""Preserve one client operation key through explicit manual trade requests."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import ValidationError
from agomtradepro.transport import use_request_transport


class _RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> Mock:
        self.calls.append(kwargs)
        return Mock(status_code=200, json=lambda: {"success": True, "trade": {"trade_id": 19}})


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_execute_trade_forwards_the_same_operation_key_and_explicit_asset_type(side: str) -> None:
    transport = _RecordingTransport()
    client = AgomTradeProClient(base_url="https://fixture.example.test", api_token="fixture-only")

    with use_request_transport(transport):
        for _ in range(2):
            result = client.simulated_trading.execute_trade(
                account_id=7,
                asset_code="600000.SH",
                asset_type="equity",
                side=side,
                quantity=100,
                price=10.25,
                idempotency_key="fixture-user-operation-1",
            )
            assert result == {"success": True, "trade": {"trade_id": 19}}

    assert len(transport.calls) == 2
    assert transport.calls[0]["json"] == transport.calls[1]["json"]
    for call in transport.calls:
        assert call["method"] == "POST"
        assert call["url"].endswith("/api/simulated-trading/accounts/7/trade/")
        assert call["headers"]["Idempotency-Key"] == "fixture-user-operation-1"
        assert call["json"]["asset_code"] == "600000.SH"
        assert call["json"]["asset_type"] == "equity"
        assert call["json"]["action"] == side
        assert call["json"]["price"] == 10.25
        assert "idempotency_key" not in call["json"]


def test_distinct_intended_trades_keep_the_callers_distinct_keys() -> None:
    transport = _RecordingTransport()
    client = AgomTradeProClient(base_url="https://fixture.example.test", api_token="fixture-only")
    with use_request_transport(transport):
        for operation_key in ("fixture-operation-1", "fixture-operation-2"):
            client.simulated_trading.execute_trade(
                account_id=7,
                asset_code="600000.SH",
                asset_type="equity",
                side="buy",
                quantity=100,
                price=10.25,
                idempotency_key=operation_key,
            )
    assert [call["headers"]["Idempotency-Key"] for call in transport.calls] == [
        "fixture-operation-1",
        "fixture-operation-2",
    ]


@pytest.mark.parametrize("operation_key", ["", " ", "x" * 129, None, True])
def test_invalid_operation_key_does_not_send_a_trade(operation_key: object) -> None:
    transport = _RecordingTransport()
    client = AgomTradeProClient(base_url="https://fixture.example.test", api_token="fixture-only")
    with use_request_transport(transport), pytest.raises(ValidationError):
        client.simulated_trading.execute_trade(
            account_id=7,
            asset_code="600000.SH",
            asset_type="equity",
            side="buy",
            quantity=100,
            price=10.25,
            idempotency_key=operation_key,
        )
    assert transport.calls == []


def test_missing_price_is_not_an_implicit_market_order() -> None:
    transport = _RecordingTransport()
    client = AgomTradeProClient(base_url="https://fixture.example.test", api_token="fixture-only")
    with use_request_transport(transport), pytest.raises(ValidationError):
        client.simulated_trading.execute_trade(
            account_id=7,
            asset_code="600000.SH",
            asset_type="equity",
            side="buy",
            quantity=100,
            price=None,
            idempotency_key="fixture-operation-without-price",
        )
    assert transport.calls == []
