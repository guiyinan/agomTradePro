"""Preserve one client operation key through explicit manual trade requests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest
import requests

import agomtradepro.exceptions as sdk_exceptions
from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import (
    AgomTradeProAPIError,
    ExecutionOutcomeUnknownError,
    ValidationError,
)
from agomtradepro.transport import use_request_transport


class _RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> Mock:
        self.calls.append(kwargs)
        return Mock(status_code=200, json=lambda: {"success": True, "trade": {"trade_id": 19}})


class _SequencedTransport:
    def __init__(self, outcomes: list[BaseException | Mock]) -> None:
        self.calls: list[dict[str, Any]] = []
        self.outcomes = outcomes

    def request(self, **kwargs: Any) -> Mock:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FailFastTransport:
    def request(self, **kwargs: Any) -> Any:
        raise AssertionError("SDK tests must not make an unconfigured network request")


def _close_success_response(
    *,
    account_id: int = 7,
    asset_code: str = "600000.SH",
    close_shares: int = 100,
    close_price: str = "10.2500",
    idempotency_key: str = "close-operation-1",
    trade_id: int = 19,
    replayed: bool = False,
) -> dict[str, Any]:
    amount = f"{Decimal(close_shares) * Decimal(close_price):.2f}"
    return {
        "success": True,
        "trade": {
            "trade_id": trade_id,
            "account_id": account_id,
            "asset_code": asset_code,
            "asset_name": asset_code,
            "asset_type": "equity",
            "action": "sell",
            "quantity": close_shares,
            "price": close_price,
            "amount": amount,
            "commission": "0.0000",
            "slippage": "0.0000",
            "total_cost": "0.00",
            "fee_amounts_known": True,
            "fee_amounts_status": "known",
            "cost_basis_known": False,
            "cost_basis_status": "unknown",
            "realized_pnl_known": False,
            "realized_pnl_status": "unknown",
            "realized_pnl_pct_known": False,
            "realized_pnl": None,
            "realized_pnl_pct": None,
            "reason": "caller-requested close",
            "signal_id": None,
            "order_date": "2026-10-22",
            "execution_date": "2026-10-22",
            "execution_time": "2026-10-22T01:00:00Z",
            "status": "executed",
        },
        "receipt": {
            "trade_id": trade_id,
            "account_id": account_id,
            "idempotency_key": idempotency_key,
            "request_payload_hash": "a" * 64,
            "side": "sell",
            "asset_code": asset_code,
            "quantity": f"{close_shares}.000000",
            "price": close_price,
            "amount": amount,
            "commission": "0.00",
            "transfer_fee": "0.00",
            "stamp_duty": "0.00",
            "slippage": "0.00",
            "total_cost": "0.00",
            "settlement_status": None,
            "settlement_release_date": None,
            "replayed": replayed,
        },
        "replayed": replayed,
    }


@pytest.fixture(autouse=True)
def _fail_fast_unconfigured_sdk_network() -> Iterator[None]:
    with use_request_transport(_FailFastTransport()):
        yield


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


def test_close_position_preserves_exact_terms_and_key_on_same_operation_retry() -> None:
    first_response = _close_success_response(replayed=False)
    second_response = _close_success_response(replayed=True)
    transport = _SequencedTransport(
        [
            Mock(status_code=200, json=lambda: first_response),
            Mock(status_code=200, json=lambda: second_response),
        ]
    )
    client = AgomTradeProClient(base_url="https://fixture.example.test", api_token="fixture-only")
    close_request = {
        "account_id": 7,
        "asset_code": "600000.SH",
        "close_shares": 100,
        "close_price": "10.2500",
        "idempotency_key": "close-operation-1",
    }

    with use_request_transport(transport):
        first = client.simulated_trading.close_position(**close_request)
        second = client.simulated_trading.close_position(**close_request)

    assert first == first_response
    assert second == second_response
    assert len(transport.calls) == 2
    assert (
        transport.calls[0]["json"]
        == transport.calls[1]["json"]
        == {
            "asset_code": "600000.SH",
            "close_shares": 100,
            "close_price": "10.2500",
        }
    )
    for call in transport.calls:
        assert call["method"] == "POST"
        assert call["url"].endswith("/api/simulated-trading/accounts/7/positions/close/")
        assert call["headers"]["Idempotency-Key"] == "close-operation-1"


def test_close_position_converts_client_timeout_to_unknown_before_same_key_retry() -> None:
    replay = _close_success_response(replayed=True)
    transport = _SequencedTransport(
        [
            sdk_exceptions.TimeoutError("response body read timed out"),
            Mock(status_code=200, json=lambda: replay),
        ]
    )
    client = AgomTradeProClient(base_url="https://fixture.example.test", api_token="fixture-only")
    close_request = {
        "account_id": 7,
        "asset_code": "600000.SH",
        "close_shares": 100,
        "close_price": "10.2500",
        "idempotency_key": "close-operation-1",
    }

    with use_request_transport(transport):
        with pytest.raises(ExecutionOutcomeUnknownError) as raised:
            client.simulated_trading.close_position(**close_request)
        assert raised.value.code == "execution_outcome_unknown"
        assert raised.value.__cause__ is None
        result = client.simulated_trading.close_position(**close_request)

    assert result == replay
    assert len(transport.calls) == 2
    assert transport.calls[0]["json"] == transport.calls[1]["json"]
    assert [call["headers"]["Idempotency-Key"] for call in transport.calls] == [
        "close-operation-1",
        "close-operation-1",
    ]


@pytest.mark.parametrize(
    "first_outcome",
    [
        "chunked_read_error",
        "read_timeout",
        "invalid_json",
        "non_object_json",
        "empty_success",
        "missing_receipt",
        "mismatched_receipt",
        "missing_trade_status",
        "pending_trade_status",
        "missing_trade_amount",
        "missing_trade_commission",
        "missing_trade_slippage",
        "missing_trade_total_cost",
        "mismatched_trade_amount",
        "mismatched_trade_commission",
        "mismatched_trade_slippage",
        "mismatched_trade_total_cost",
        "nonfinite_trade_commission",
        "negative_receipt_transfer_fee",
        "receipt_total_cost_does_not_equal_fees",
        "receipt_amount_does_not_match_terms",
        "sell_receipt_with_settlement_state",
        "receipt_subcent_commission",
        "receipt_money_at_exclusive_max",
        "receipt_huge_finite_exponent",
        "receipt_money_quantize_overflow",
    ],
)
def test_close_unknown_readback_retries_same_body_and_key(
    first_outcome: str,
) -> None:
    valid_replay = _close_success_response(replayed=True)
    if first_outcome == "chunked_read_error":
        first_response: BaseException | Mock = requests.exceptions.ChunkedEncodingError(
            "truncated response body"
        )
    elif first_outcome == "read_timeout":
        first_response = requests.exceptions.ReadTimeout("response body read timed out")
    elif first_outcome == "invalid_json":
        first_response = Mock(status_code=200, json=Mock(side_effect=ValueError("not JSON")))
    elif first_outcome == "non_object_json":
        first_response = Mock(status_code=200, json=lambda: ["success", True])
    elif first_outcome == "empty_success":
        first_response = Mock(status_code=200, json=lambda: {})
    elif first_outcome == "missing_receipt":
        malformed_response = dict(valid_replay)
        malformed_response.pop("receipt")
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome == "mismatched_receipt":
        malformed_response = dict(valid_replay)
        malformed_receipt = dict(valid_replay["receipt"])
        malformed_receipt["idempotency_key"] = "different-operation"
        malformed_response["receipt"] = malformed_receipt
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome in {"missing_trade_status", "pending_trade_status"}:
        malformed_response = dict(valid_replay)
        malformed_trade = dict(valid_replay["trade"])
        if first_outcome == "missing_trade_status":
            malformed_trade.pop("status")
        else:
            malformed_trade["status"] = "pending"
        malformed_response["trade"] = malformed_trade
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome.startswith("missing_trade_"):
        malformed_response = dict(valid_replay)
        malformed_trade = dict(valid_replay["trade"])
        malformed_trade.pop(first_outcome.removeprefix("missing_trade_"))
        malformed_response["trade"] = malformed_trade
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome.startswith("mismatched_trade_"):
        malformed_response = dict(valid_replay)
        malformed_trade = dict(valid_replay["trade"])
        field = first_outcome.removeprefix("mismatched_trade_")
        malformed_trade[field] = str(Decimal(malformed_trade[field]) + Decimal("0.01"))
        malformed_response["trade"] = malformed_trade
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome == "nonfinite_trade_commission":
        malformed_response = dict(valid_replay)
        malformed_trade = dict(valid_replay["trade"])
        malformed_trade["commission"] = "NaN"
        malformed_response["trade"] = malformed_trade
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome == "negative_receipt_transfer_fee":
        malformed_response = dict(valid_replay)
        malformed_receipt = dict(valid_replay["receipt"])
        malformed_receipt["transfer_fee"] = "-0.01"
        malformed_response["receipt"] = malformed_receipt
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome == "receipt_total_cost_does_not_equal_fees":
        malformed_response = dict(valid_replay)
        malformed_trade = dict(valid_replay["trade"])
        malformed_trade["commission"] = "0.0100"
        malformed_response["trade"] = malformed_trade
        malformed_receipt = dict(valid_replay["receipt"])
        malformed_receipt["commission"] = "0.01"
        malformed_response["receipt"] = malformed_receipt
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome == "receipt_amount_does_not_match_terms":
        malformed_response = dict(valid_replay)
        malformed_trade = dict(valid_replay["trade"])
        malformed_trade["amount"] = str(Decimal(malformed_trade["amount"]) + Decimal("0.01"))
        malformed_response["trade"] = malformed_trade
        malformed_receipt = dict(valid_replay["receipt"])
        malformed_receipt["amount"] = str(Decimal(malformed_receipt["amount"]) + Decimal("0.01"))
        malformed_response["receipt"] = malformed_receipt
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome == "sell_receipt_with_settlement_state":
        malformed_response = dict(valid_replay)
        malformed_receipt = dict(valid_replay["receipt"])
        malformed_receipt["settlement_status"] = "pending"
        malformed_response["receipt"] = malformed_receipt
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome == "receipt_subcent_commission":
        malformed_response = dict(valid_replay)
        malformed_trade = dict(valid_replay["trade"])
        malformed_trade["commission"] = "0.001"
        malformed_trade["total_cost"] = "0.001"
        malformed_response["trade"] = malformed_trade
        malformed_receipt = dict(valid_replay["receipt"])
        malformed_receipt["commission"] = "0.001"
        malformed_receipt["total_cost"] = "0.001"
        malformed_response["receipt"] = malformed_receipt
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome == "receipt_money_at_exclusive_max":
        malformed_response = dict(valid_replay)
        malformed_trade = dict(valid_replay["trade"])
        malformed_trade["commission"] = "10000000000000.00"
        malformed_trade["total_cost"] = "10000000000000.00"
        malformed_response["trade"] = malformed_trade
        malformed_receipt = dict(valid_replay["receipt"])
        malformed_receipt["commission"] = "10000000000000.00"
        malformed_receipt["total_cost"] = "10000000000000.00"
        malformed_response["receipt"] = malformed_receipt
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    elif first_outcome in {"receipt_huge_finite_exponent", "receipt_money_quantize_overflow"}:
        malformed_response = dict(valid_replay)
        malformed_trade = dict(valid_replay["trade"])
        malformed_receipt = dict(valid_replay["receipt"])
        amount = "1e64" if first_outcome == "receipt_huge_finite_exponent" else f"{'9' * 64}e64"
        malformed_trade["commission"] = amount
        malformed_trade["total_cost"] = amount
        malformed_response["trade"] = malformed_trade
        malformed_receipt["commission"] = amount
        malformed_receipt["total_cost"] = amount
        malformed_response["receipt"] = malformed_receipt
        first_response = Mock(status_code=200, json=lambda: malformed_response)
    else:
        raise AssertionError(f"Unsupported first outcome: {first_outcome}")
    transport = _SequencedTransport(
        [first_response, Mock(status_code=200, json=lambda: valid_replay)]
    )
    client = AgomTradeProClient(base_url="https://fixture.example.test", api_token="fixture-only")
    close_request = {
        "account_id": 7,
        "asset_code": "600000.SH",
        "close_shares": 100,
        "close_price": "10.2500",
        "idempotency_key": "close-operation-1",
    }

    with use_request_transport(transport):
        with pytest.raises(ExecutionOutcomeUnknownError) as raised:
            client.simulated_trading.close_position(**close_request)

        assert raised.value.status_code is None
        assert raised.value.response is None
        assert raised.value.code == "execution_outcome_unknown"
        assert raised.value.effects_indeterminate is True
        assert "truncated response body" not in str(raised.value)

        completed = client.simulated_trading.close_position(**close_request)
    assert completed == valid_replay
    assert len(transport.calls) == 2
    assert (
        transport.calls[0]["json"]
        == transport.calls[1]["json"]
        == {
            "asset_code": "600000.SH",
            "close_shares": 100,
            "close_price": "10.2500",
        }
    )
    assert [call["headers"]["Idempotency-Key"] for call in transport.calls] == [
        "close-operation-1",
        "close-operation-1",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"close_shares": True},
        {"close_shares": 0},
        {"close_shares": 100000000000000},
        {"close_price": 10.25},
        {"close_price": "1e1"},
        {"close_price": "0.001"},
        {"close_price": "1000000"},
        {"idempotency_key": "bad key"},
    ],
)
def test_close_position_rejects_noncanonical_terms_before_request(changes: dict[str, Any]) -> None:
    transport = _RecordingTransport()
    client = AgomTradeProClient(base_url="https://fixture.example.test", api_token="fixture-only")
    close_request: dict[str, Any] = {
        "account_id": 7,
        "asset_code": "600000.SH",
        "close_shares": 100,
        "close_price": "10.2500",
        "idempotency_key": "close-operation-1",
    }
    close_request.update(changes)

    with use_request_transport(transport), pytest.raises(ValidationError):
        client.simulated_trading.close_position(**close_request)

    assert transport.calls == []


def test_close_position_preserves_indeterminate_503_response_for_caller() -> None:
    unknown_body = {
        "success": False,
        "error": "平仓结果暂无法确认，请使用相同请求和幂等键重试。",
        "code": "SIMULATED_TRADE_EXECUTION_READBACK_UNKNOWN",
        "effects_indeterminate": True,
        "request_id": "req-close-1",
    }

    class _UnknownResponseTransport:
        def request(self, **kwargs: Any) -> Mock:
            return Mock(status_code=503, json=lambda: unknown_body)

    client = AgomTradeProClient(base_url="https://fixture.example.test", api_token="fixture-only")
    with (
        use_request_transport(_UnknownResponseTransport()),
        pytest.raises(AgomTradeProAPIError) as raised,
    ):
        client.simulated_trading.close_position(
            account_id=7,
            asset_code="600000.SH",
            close_shares=100,
            close_price="10.2500",
            idempotency_key="close-operation-1",
        )

    assert raised.value.status_code == 503
    assert raised.value.response == unknown_body


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


def test_run_auto_trading_forwards_the_callers_operation_key_as_http_header() -> None:
    transport = _RecordingTransport()
    client = AgomTradeProClient(base_url="https://fixture.example.test", api_token="fixture-only")
    operation_key = "fixture-auto-run-operation-1"

    with use_request_transport(transport):
        for _ in range(2):
            result = client.simulated_trading.run_auto_trading(
                trade_date=date(2026, 10, 19),
                account_ids=[7, 9],
                idempotency_key=operation_key,
            )
            assert result == {"success": True, "trade": {"trade_id": 19}}

    assert len(transport.calls) == 2
    for call in transport.calls:
        assert call["method"] == "POST"
        assert call["url"].endswith("/api/simulated-trading/auto-trading/run/")
        assert call["headers"]["Idempotency-Key"] == operation_key
        assert call["json"] == {"trade_date": "2026-10-19", "account_ids": [7, 9]}
        assert "idempotency_key" not in call["json"]
