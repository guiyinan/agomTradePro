"""Keep one caller-owned auto-run key intact across MCP SDK boundaries."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from agomtradepro.transport import use_request_transport


class _CapturingServer:
    """Register local MCP tool functions without starting a transport."""

    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {}

    def tool(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Capture each decorated tool function by its public Python name."""

        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            self.tools[function.__name__] = function
            return function

        return register


class _FailFastTransport:
    def request(self, **kwargs: Any) -> Any:
        raise AssertionError("MCP unit tests must not make an unconfigured SDK request")


def _close_success_response(
    *,
    account_id: int = 7,
    asset_code: str = "600000.SH",
    close_shares: int = 100,
    close_price: str = "10.2500",
    idempotency_key: str = "close-operation-1",
    trade_id: int = 31,
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
            "total_cost": amount,
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
            "total_cost": amount,
            "settlement_status": "settled",
            "settlement_release_date": None,
            "replayed": replayed,
        },
        "replayed": replayed,
    }


@pytest.fixture(autouse=True)
def _fail_fast_unconfigured_sdk_network() -> Iterator[None]:
    with use_request_transport(_FailFastTransport()):
        yield


def test_auto_trading_runtime_fallback_forwards_the_same_key_to_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro
    from agomtradepro_mcp.registry.runtime_handlers.owners.simulated_trading import (
        _fallback_run_simulated_auto_trading,
    )

    calls: list[dict[str, Any]] = []

    def run_auto_trading(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return {"success": True, "accepted": True}

    simulated_trading = SimpleNamespace(run_auto_trading=run_auto_trading)
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(simulated_trading=simulated_trading),
    )
    operation_key = "mcp-auto-run-operation-20261019-a"

    result = _fallback_run_simulated_auto_trading(
        trade_date="2026-10-19",
        account_ids=[7, 9],
        idempotency_key=operation_key,
    )

    assert result == {"success": True, "accepted": True}
    assert calls == [
        {
            "trade_date": date(2026, 10, 19),
            "account_ids": [7, 9],
            "idempotency_key": operation_key,
        }
    ]


def test_raw_legacy_auto_trading_tool_requires_and_forwards_caller_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro_mcp.tools.simulated_trading_tools as tools_module

    server = _CapturingServer()
    calls: list[dict[str, Any]] = []
    client_creations: list[bool] = []

    def run_auto_trading(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return {"success": True, "accepted": True}

    def build_client() -> SimpleNamespace:
        client_creations.append(True)
        simulated_trading = SimpleNamespace(run_auto_trading=run_auto_trading)
        return SimpleNamespace(simulated_trading=simulated_trading)

    monkeypatch.setattr(tools_module, "AgomTradeProClient", build_client)
    tools_module.register_simulated_trading_tools(server)
    operation_key = "legacy-mcp-auto-run-operation-20261019-a"
    raw_tool = server.tools["run_simulated_auto_trading"]

    with pytest.raises(TypeError):
        raw_tool(trade_date="2026-10-19", account_ids=[7, 9])
    assert client_creations == []
    assert calls == []

    result = raw_tool(
        trade_date="2026-10-19",
        account_ids=[7, 9],
        idempotency_key=operation_key,
    )

    assert result == {"success": True, "accepted": True}
    assert calls == [
        {
            "trade_date": date(2026, 10, 19),
            "account_ids": [7, 9],
            "idempotency_key": operation_key,
        }
    ]


def test_raw_close_tool_forwards_exact_terms_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import agomtradepro_mcp.tools.simulated_trading_tools as tools_module

    calls: list[dict[str, Any]] = []
    response = _close_success_response()

    def close_position(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return response

    monkeypatch.setattr(
        tools_module,
        "AgomTradeProClient",
        lambda: SimpleNamespace(simulated_trading=SimpleNamespace(close_position=close_position)),
    )
    server = _CapturingServer()
    tools_module.register_simulated_trading_tools(server)
    raw_tool = server.tools["close_simulated_position"]

    with pytest.raises(TypeError):
        raw_tool(account_id=7, asset_code="600000.SH", close_shares=100, close_price="10.2500")

    result = raw_tool(
        account_id=7,
        asset_code="600000.SH",
        close_shares=100,
        close_price="10.2500",
        idempotency_key="close-operation-1",
    )

    assert result is response
    assert calls == [
        {
            "account_id": 7,
            "asset_code": "600000.SH",
            "close_shares": 100,
            "close_price": "10.2500",
            "idempotency_key": "close-operation-1",
        }
    ]


def test_runtime_close_fallback_forwards_exact_terms_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro
    from agomtradepro_mcp.registry.runtime_handlers.owners.simulated_trading import (
        _fallback_close_simulated_position,
    )

    calls: list[dict[str, Any]] = []

    def close_position(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return _close_success_response()

    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(simulated_trading=SimpleNamespace(close_position=close_position)),
    )

    result = _fallback_close_simulated_position(
        account_id=7,
        asset_code="600000.SH",
        close_shares=100,
        close_price="10.2500",
        idempotency_key="close-operation-1",
    )

    assert result["trade"]["trade_id"] == 31
    assert calls == [
        {
            "account_id": 7,
            "asset_code": "600000.SH",
            "close_shares": 100,
            "close_price": "10.2500",
            "idempotency_key": "close-operation-1",
        }
    ]


def test_raw_close_tool_does_not_convert_unknown_api_response_to_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro_mcp.tools.simulated_trading_tools as tools_module
    from agomtradepro.exceptions import ServerError

    unknown_body = {
        "code": "SIMULATED_TRADE_EXECUTION_READBACK_UNKNOWN",
        "effects_indeterminate": True,
        "message": "same-key retry required",
    }
    unknown_error = ServerError(
        message="readback is unknown",
        status_code=503,
        response=unknown_body,
    )

    calls: list[dict[str, Any]] = []
    attempts = 0

    def close_position(**_kwargs: Any) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        calls.append(dict(_kwargs))
        if attempts == 1:
            raise unknown_error
        return _close_success_response(replayed=True)

    monkeypatch.setattr(
        tools_module,
        "AgomTradeProClient",
        lambda: SimpleNamespace(simulated_trading=SimpleNamespace(close_position=close_position)),
    )
    server = _CapturingServer()
    tools_module.register_simulated_trading_tools(server)

    close_request = {
        "account_id": 7,
        "asset_code": "600000.SH",
        "close_shares": 100,
        "close_price": "10.2500",
        "idempotency_key": "close-operation-1",
    }
    unknown = server.tools["close_simulated_position"](**close_request)

    assert unknown["success"] is False
    assert unknown["status"] == "unknown"
    assert unknown["effects_indeterminate"] is True
    assert unknown["retry_with_same_idempotency_key"] is True
    assert unknown["idempotency_key"] == close_request["idempotency_key"]
    assert unknown["upstream_response"] == unknown_body
    assert unknown["upstream_response"] is not unknown_body

    completed = server.tools["close_simulated_position"](**close_request)
    assert completed["trade"]["trade_id"] == 31
    assert completed["receipt"]["idempotency_key"] == close_request["idempotency_key"]
    assert completed["replayed"] is True
    assert calls == [close_request, close_request]


@pytest.mark.parametrize(
    (
        "status_code",
        "response",
        "message",
        "expected_code",
        "preserve_upstream_response",
    ),
    [
        pytest.param(
            500,
            None,
            "<html>traceback password=secret</html>",
            "upstream_http_5xx",
            False,
            id="html-body-is-not-disclosed",
        ),
        pytest.param(
            502,
            {"code": "gateway_overload", "detail": "traceback token=secret"},
            "gateway error",
            "gateway_overload",
            False,
            id="structured-code-preserved-body-redacted",
        ),
        pytest.param(
            503,
            {
                "code": "gateway_readback_unknown",
                "effects_indeterminate": True,
                "message": "<html>traceback token=secret</html>",
            },
            "readback uncertain",
            "gateway_readback_unknown",
            False,
            id="unsafe-marked-503-body-redacted",
        ),
        pytest.param(
            503,
            {
                "code": "token=secret",
                "effects_indeterminate": True,
                "request_id": "req-close-unsafe-code",
            },
            "readback uncertain",
            "upstream_http_5xx",
            False,
            id="unsafe-marked-503-code-redacted",
        ),
        pytest.param(
            504,
            {"effects_indeterminate": False},
            "gateway timeout",
            "upstream_http_5xx",
            False,
            id="missing-indeterminate-marker-is-still-unknown",
        ),
        pytest.param(
            503,
            {
                "success": False,
                "error": "平仓结果暂无法确认，请使用相同请求和幂等键重试。",
                "code": "SIMULATED_TRADE_EXECUTION_READBACK_UNKNOWN",
                "effects_indeterminate": True,
                "request_id": "req-close-backend-unknown",
            },
            "readback uncertain",
            "simulated_trade_execution_readback_unknown",
            True,
            id="actual-backend-readback-unknown-envelope",
        ),
        pytest.param(
            503,
            {
                "success": True,
                "error": "平仓结果暂无法确认。",
                "code": "gateway_readback_unknown",
                "effects_indeterminate": True,
            },
            "readback uncertain",
            "gateway_readback_unknown",
            False,
            id="marked-503-rejects-non-false-success",
        ),
        pytest.param(
            503,
            {
                "success": 0,
                "error": "平仓结果暂无法确认。",
                "code": "gateway_readback_unknown",
                "effects_indeterminate": True,
            },
            "readback uncertain",
            "gateway_readback_unknown",
            False,
            id="marked-503-rejects-integer-success",
        ),
        pytest.param(
            503,
            {
                "success": False,
                "error": 503,
                "code": "gateway_readback_unknown",
                "effects_indeterminate": True,
            },
            "readback uncertain",
            "gateway_readback_unknown",
            False,
            id="marked-503-rejects-non-string-error",
        ),
        pytest.param(
            503,
            {
                "success": False,
                "error": "https://internal.example.test/diagnostic",
                "code": "gateway_readback_unknown",
                "effects_indeterminate": True,
            },
            "readback uncertain",
            "gateway_readback_unknown",
            False,
            id="marked-503-redacts-uri-error",
        ),
    ],
)
def test_raw_close_treats_http_5xx_as_unknown_without_leaking_body(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    response: dict[str, Any] | None,
    message: str,
    expected_code: str,
    preserve_upstream_response: bool,
) -> None:
    import agomtradepro_mcp.tools.simulated_trading_tools as tools_module
    from agomtradepro.exceptions import ServerError

    uncertain_error = ServerError(
        message=message,
        status_code=status_code,
        response=response,
    )

    def close_position(**_kwargs: Any) -> dict[str, Any]:
        raise uncertain_error

    monkeypatch.setattr(
        tools_module,
        "AgomTradeProClient",
        lambda: SimpleNamespace(simulated_trading=SimpleNamespace(close_position=close_position)),
    )
    server = _CapturingServer()
    tools_module.register_simulated_trading_tools(server)

    result = server.tools["close_simulated_position"](
        account_id=7,
        asset_code="600000.SH",
        close_shares=100,
        close_price="10.2500",
        idempotency_key="close-operation-1",
    )

    assert result["status"] == "unknown"
    assert result["effects_indeterminate"] is True
    assert result["retry_with_same_idempotency_key"] is True
    assert result["idempotency_key"] == "close-operation-1"
    assert result["error"]["code"] == expected_code
    assert result["error"]["upstream_status_code"] == status_code
    if preserve_upstream_response:
        assert result["upstream_response"] == response
    else:
        assert "upstream_response" not in result
    assert "traceback" not in repr(result).lower()
    assert "secret" not in repr(result).lower()


def test_raw_close_preserves_typed_unknown_as_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro_mcp.tools.simulated_trading_tools as tools_module
    from agomtradepro.exceptions import ExecutionOutcomeUnknownError

    def close_position(**_kwargs: Any) -> dict[str, Any]:
        raise ExecutionOutcomeUnknownError()

    monkeypatch.setattr(
        tools_module,
        "AgomTradeProClient",
        lambda: SimpleNamespace(simulated_trading=SimpleNamespace(close_position=close_position)),
    )
    server = _CapturingServer()
    tools_module.register_simulated_trading_tools(server)

    result = server.tools["close_simulated_position"](
        account_id=7,
        asset_code="600000.SH",
        close_shares=100,
        close_price="10.2500",
        idempotency_key="close-operation-1",
    )

    assert result["success"] is False
    assert result["status"] == "unknown"
    assert result["effects_indeterminate"] is True
    assert result["retry_with_same_idempotency_key"] is True
    assert result["idempotency_key"] == "close-operation-1"
    assert result["error"]["code"] == "execution_outcome_unknown"
    assert "upstream_status_code" not in result["error"]
    assert "结果尚未核实" in str(result["error"]["message"])


@pytest.mark.parametrize("status_code", [400, 403, 409])
def test_raw_close_does_not_reclassify_definitive_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    import agomtradepro_mcp.tools.simulated_trading_tools as tools_module
    from agomtradepro.exceptions import AgomTradeProAPIError

    definitive_error = AgomTradeProAPIError(
        message="definitive request rejection",
        status_code=status_code,
        response={"code": "request_rejected", "effects_indeterminate": True},
    )

    def close_position(**_kwargs: Any) -> dict[str, Any]:
        raise definitive_error

    monkeypatch.setattr(
        tools_module,
        "AgomTradeProClient",
        lambda: SimpleNamespace(simulated_trading=SimpleNamespace(close_position=close_position)),
    )
    server = _CapturingServer()
    tools_module.register_simulated_trading_tools(server)

    with pytest.raises(AgomTradeProAPIError) as raised:
        server.tools["close_simulated_position"](
            account_id=7,
            asset_code="600000.SH",
            close_shares=100,
            close_price="10.2500",
            idempotency_key="close-operation-1",
        )

    assert raised.value is definitive_error
