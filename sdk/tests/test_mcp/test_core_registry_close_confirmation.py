"""Close confirmation and indeterminate-result tests for MCP simulated trading."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

import agomtradepro.exceptions as sdk_exceptions
from agomtradepro.transport import use_request_transport

from .core_registry_support import (
    _capture_governed_audit_events,
)
from .core_registry_support import (
    _isolate_core_dispatcher_boundaries as _isolate_core_dispatcher_boundaries,
)


class _FailFastTransport:
    def request(self, **kwargs: Any) -> Any:
        raise AssertionError("MCP unit tests must not make an unconfigured SDK request")


def _close_success_response(
    *,
    account_id: int = 7,
    asset_code: str = "510300.SH",
    close_shares: int = 100,
    close_price: str = "4.1200",
    idempotency_key: str = "close-operation-1",
    trade_id: int = 7001,
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


def test_trading_close_simulated_position_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id):
            return {
                "id": account_id,
                "name": "Alpha Sim",
                "status": "active",
                "account_type": "simulated",
            }

        @staticmethod
        def get_positions(account_id, asset_code=None):
            assert account_id == 7
            assert asset_code == "510300.SH"
            return [
                {
                    "asset_code": "510300.SH",
                    "quantity": 1200,
                    "available_quantity": 800,
                    "avg_cost": 3.82,
                }
            ]

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_close_simulated_position(**kwargs):
        captured_calls.append(dict(kwargs))
        return _close_success_response(
            account_id=kwargs["account_id"],
            asset_code=kwargs["asset_code"],
            close_shares=kwargs["close_shares"],
            close_price=kwargs["close_price"],
            idempotency_key=kwargs["idempotency_key"],
            trade_id=7001,
            replayed=False,
        )

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "close_simulated_position",
        fake_close_simulated_position,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="trading.close.simulated_position",
        arguments={
            "account_id": 7,
            "asset_code": "510300.SH",
            "close_shares": 300,
            "close_price": "4.1250",
            "idempotency_key": "idem-simulated-close",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["account_summary"]["account_name"] == "Alpha Sim"
    assert preview_response["preview_result"]["requested_close_shares"] == 300
    assert preview_response["preview_result"]["requested_close_price"] == "4.1250"
    assert preview_response["preview_result"]["intent"] == "sell"
    assert preview_response["preview_result"]["position_summary"] == {
        "matched_position_count": 1,
        "available_quantity": 800,
    }
    assert "current_quantity" not in preview_response["preview_result"]["position_summary"]
    assert "average_cost" not in preview_response["preview_result"]["position_summary"]
    assert "target_status" not in preview_response["preview_result"]
    assert captured_calls == []
    close_manifest = server_module.CORE_DISPATCHER._registry["trading.close.simulated_position"]
    close_schema = close_manifest.to_schema_dict()
    assert close_manifest.preserve_confirmation_on_indeterminate_outcome is True
    assert close_schema["input_schema"]["required"] == [
        "account_id",
        "asset_code",
        "close_shares",
        "close_price",
        "idempotency_key",
    ]
    assert "order_id" not in close_schema["output_schema"]["properties"]
    assert "closed" not in close_schema["output_schema"]["properties"]
    assert "remaining_quantity" not in close_schema["output_schema"]["properties"]
    assert close_schema["output_schema"]["oneOf"][0]["required"] == [
        "trade",
        "receipt",
        "replayed",
    ]
    assert "effects_indeterminate" in close_schema["output_schema"]["oneOf"][1]["required"]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["trade"]["trade_id"] == 7001
    assert resume_response["result"]["receipt"]["trade_id"] == 7001
    assert resume_response["result"]["replayed"] is False
    assert resume_response["idempotency_key"] == "idem-simulated-close"
    assert captured_calls == [
        {
            "account_id": 7,
            "asset_code": "510300.SH",
            "close_shares": 300,
            "close_price": "4.1250",
            "idempotency_key": "idem-simulated-close",
        }
    ]
    assert audit_events[0]["affected_objects"]["account_id"] == 7
    assert audit_events[0]["affected_objects"]["asset_code"] == "510300.SH"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_close_preview_does_not_infer_available_quantity_from_position_total(
    monkeypatch: pytest.MonkeyPatch,
):
    from agomtradepro_mcp.registry.runtime_handlers.owners import (
        simulated_trading as runtime_module,
    )

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id):
            assert account_id == 7
            return {"id": account_id, "name": "Alpha Sim", "status": "active"}

        @staticmethod
        def get_positions(account_id, asset_code=None):
            assert account_id == 7
            assert asset_code == "510300.SH"
            return [{"asset_code": asset_code, "quantity": 1200, "avg_cost": 3.82}]

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    preview = runtime_module._internal_handler_trading_close_simulated_position(
        account_id=7,
        asset_code="510300.SH",
        close_shares=300,
        close_price="4.1250",
        idempotency_key="idem-simulated-close-missing-availability",
        preview_only=True,
    )

    assert preview["position_summary"] == {
        "matched_position_count": 1,
        "available_quantity": None,
    }


@pytest.mark.parametrize(
    ("failure", "error_code", "preserve_upstream_response"),
    [
        pytest.param(
            sdk_exceptions.ServerError(
                message="<html>traceback token=secret</html>",
                status_code=500,
                response=None,
            ),
            "capability_execution_failed",
            False,
            id="typed-500-without-effects-marker",
        ),
        pytest.param(
            sdk_exceptions.ServerError(
                message="readback is unknown",
                status_code=503,
                response={
                    "success": False,
                    "error": "平仓结果暂无法确认，请使用相同请求和幂等键重试。",
                    "code": "SIMULATED_TRADE_EXECUTION_READBACK_UNKNOWN",
                    "effects_indeterminate": True,
                    "request_id": "req-close-unknown-1",
                },
            ),
            "simulated_trade_execution_readback_unknown",
            True,
            id="typed-503-readback-unknown",
        ),
        pytest.param(
            sdk_exceptions.ServerError(
                message="<html>traceback password=secret</html>",
                status_code=502,
                response={
                    "code": "gateway_overload",
                    "detail": "traceback token=secret",
                },
            ),
            "gateway_overload",
            False,
            id="typed-502-keeps-safe-code-only",
        ),
        pytest.param(
            sdk_exceptions.ServerError(
                message="readback body is unsafe",
                status_code=503,
                response={
                    "code": "gateway_readback_unknown",
                    "effects_indeterminate": True,
                    "message": "<html>traceback token=secret</html>",
                },
            ),
            "gateway_readback_unknown",
            False,
            id="unsafe-marked-503-body-redacted",
        ),
        pytest.param(
            sdk_exceptions.ServerError(
                message="readback code is unsafe",
                status_code=503,
                response={
                    "code": "token=secret",
                    "effects_indeterminate": True,
                    "request_id": "req-unsafe-code",
                },
            ),
            "capability_execution_failed",
            False,
            id="unsafe-marked-503-code-redacted",
        ),
        pytest.param(
            sdk_exceptions.ServerError(
                message="gateway timeout after request",
                status_code=504,
                response=None,
            ),
            "capability_execution_failed",
            False,
            id="typed-504-without-effects-marker",
        ),
        pytest.param(
            sdk_exceptions.TimeoutError("response timeout"),
            "transport_timeout",
            False,
            id="transport-timeout",
        ),
        pytest.param(
            sdk_exceptions.ExecutionOutcomeUnknownError(),
            "execution_outcome_unknown",
            False,
            id="typed-unknown-readback",
        ),
        pytest.param(
            sdk_exceptions.AgomTradeProAPIError("Redirect status 302 rejected", status_code=302),
            "upstream_http_redirect",
            False,
            id="close-302-no-follow-is-unknown",
        ),
        pytest.param(
            sdk_exceptions.AgomTradeProAPIError("Redirect status 307 rejected", status_code=307),
            "upstream_http_redirect",
            False,
            id="close-307-no-follow-is-unknown",
        ),
        pytest.param(
            sdk_exceptions.AgomTradeProAPIError("Redirect status 308 rejected", status_code=308),
            "upstream_http_redirect",
            False,
            id="close-308-no-follow-is-unknown",
        ),
        pytest.param(
            sdk_exceptions.ConnectionError("connection dropped after request"),
            "transport_connection_failed",
            False,
            id="transport-disconnect",
        ),
    ],
)
def test_close_indeterminate_outcome_reuses_frozen_confirmation_and_key(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    error_code: str,
    preserve_upstream_response: bool,
) -> None:
    import agomtradepro_mcp.server as server_module

    preview_calls: list[dict[str, Any]] = []
    commit_calls: list[dict[str, Any]] = []
    captured_response = getattr(failure, "response", None)

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id: int) -> dict[str, Any]:
            preview_calls.append({"kind": "account", "account_id": account_id})
            return {"id": account_id, "name": "Alpha Sim", "status": "active"}

        @staticmethod
        def get_positions(
            account_id: int,
            asset_code: str | None = None,
        ) -> list[dict[str, Any]]:
            preview_calls.append(
                {"kind": "positions", "account_id": account_id, "asset_code": asset_code}
            )
            return [{"asset_code": asset_code, "available_quantity": 500, "avg_cost": 3.5}]

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())
    attempts = 0

    def uncertain_close(**kwargs: Any) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        commit_calls.append(dict(kwargs))
        if attempts == 1:
            raise failure
        return _close_success_response(
            account_id=kwargs["account_id"],
            asset_code=kwargs["asset_code"],
            close_shares=kwargs["close_shares"],
            close_price=kwargs["close_price"],
            idempotency_key=kwargs["idempotency_key"],
            trade_id=7010,
            replayed=True,
        )

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "close_simulated_position",
        uncertain_close,
    )
    request_arguments = {
        "account_id": 7,
        "asset_code": "510300.SH",
        "close_shares": 250,
        "close_price": "4.1200",
        "idempotency_key": "close-unknown-operation-1",
    }
    first_stage = server_module.CORE_DISPATCHER.call(
        capability_key="trading.close.simulated_position",
        arguments=request_arguments,
    )
    token = first_stage["confirmation_token"]

    unknown = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=token,
        approve=True,
    )

    assert unknown["ok"] is False
    assert unknown["status"] == "unknown"
    assert unknown["effects_indeterminate"] is True
    assert unknown["retry_with_same_idempotency_key"] is True
    assert unknown["confirmation_token"] == token
    assert unknown["idempotency_key"] == request_arguments["idempotency_key"]
    assert unknown["error"]["effects_indeterminate"] is True
    assert unknown["error"]["retry_with_same_idempotency_key"] is True
    assert unknown["error"]["code"] == error_code
    if isinstance(failure, sdk_exceptions.ExecutionOutcomeUnknownError):
        assert unknown["error"]["message"] == "执行结果尚未核实；请复用原确认与幂等键重试。"
        assert "upstream_status_code" not in unknown["error"]
    if (
        isinstance(failure, sdk_exceptions.AgomTradeProAPIError)
        and type(failure.status_code) is int
    ):
        if 300 <= failure.status_code <= 399:
            assert unknown["error"]["message"] == "执行结果尚未核实；请复用原确认与幂等键重试。"
            assert unknown["error"]["upstream_status_code"] == failure.status_code
    if preserve_upstream_response:
        assert unknown["error"]["upstream_response"] == captured_response
        assert unknown["error"]["upstream_status_code"] == 503
    else:
        assert "upstream_response" not in unknown["error"]
    if isinstance(failure, sdk_exceptions.ServerError) and failure.status_code in {502, 503}:
        assert unknown["error"]["upstream_status_code"] == failure.status_code
        assert "traceback" not in repr(unknown).lower()
        assert "secret" not in repr(unknown).lower()

    changed_terms = dict(request_arguments)
    changed_terms["close_shares"] = 251
    conflict = server_module.CORE_DISPATCHER.call(
        capability_key="trading.close.simulated_position",
        arguments=changed_terms,
    )
    assert conflict["status"] == "error"
    assert conflict["error"]["code"] == "idempotency_key_conflict"
    assert len(preview_calls) == 2
    assert attempts == 1

    reused_stage = server_module.CORE_DISPATCHER.call(
        capability_key="trading.close.simulated_position",
        arguments=request_arguments,
    )
    assert reused_stage["status"] == "confirmation_required"
    assert reused_stage["idempotency_reused"] is True
    assert reused_stage["confirmation_token"] == token
    assert len(preview_calls) == 2

    completed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=token,
        approve=True,
    )

    assert completed["status"] == "completed"
    assert completed["result"]["trade"]["trade_id"] == 7010
    assert completed["result"]["receipt"]["trade_id"] == 7010
    assert completed["result"]["replayed"] is True
    assert attempts == 2
    assert [call["idempotency_key"] for call in commit_calls] == [
        request_arguments["idempotency_key"],
        request_arguments["idempotency_key"],
    ]


@pytest.mark.parametrize("status_code", [400, 403, 409])
def test_close_definitive_http_rejection_does_not_keep_confirmation_pending(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    import agomtradepro_mcp.server as server_module

    preview_calls: list[dict[str, Any]] = []

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id: int) -> dict[str, Any]:
            preview_calls.append({"kind": "account", "account_id": account_id})
            return {"id": account_id, "name": "Alpha Sim", "status": "active"}

        @staticmethod
        def get_positions(
            account_id: int,
            asset_code: str | None = None,
        ) -> list[dict[str, Any]]:
            preview_calls.append({"kind": "positions", "account_id": account_id})
            return [{"asset_code": asset_code, "available_quantity": 500}]

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())
    attempts = 0

    def reject_close(**_kwargs: Any) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        raise sdk_exceptions.AgomTradeProAPIError(
            message="definitive request rejection",
            status_code=status_code,
            response={"code": "request_rejected", "effects_indeterminate": True},
        )

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "close_simulated_position",
        reject_close,
    )
    arguments = {
        "account_id": 7,
        "asset_code": "510300.SH",
        "close_shares": 250,
        "close_price": "4.1200",
        "idempotency_key": f"close-definitive-{status_code}",
    }

    staged = server_module.CORE_DISPATCHER.call(
        capability_key="trading.close.simulated_position",
        arguments=arguments,
    )
    original_token = staged["confirmation_token"]
    rejected = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=original_token,
        approve=True,
    )

    assert rejected["status"] == "error"
    assert rejected["error"]["code"] == "request_rejected"
    assert rejected.get("effects_indeterminate") is not True
    restaged = server_module.CORE_DISPATCHER.call(
        capability_key="trading.close.simulated_position",
        arguments=arguments,
    )
    assert restaged["status"] == "confirmation_required"
    assert restaged["confirmation_token"] != original_token
    assert len(preview_calls) == 4
    assert attempts == 1


@pytest.mark.parametrize("status_code", [302, 307, 308])
def test_raw_close_mcp_redirect_keeps_original_status_unknown_and_retry_key(
    status_code: int,
) -> None:
    from agomtradepro_mcp.tools.simulated_trading_tools import _indeterminate_close_result

    key = "close-redirect-retry-key-1"
    result = _indeterminate_close_result(
        sdk_exceptions.AgomTradeProAPIError(
            message=f"Redirect status {status_code} rejected",
            status_code=status_code,
        ),
        idempotency_key=key,
    )

    assert result == {
        "success": False,
        "status": "unknown",
        "effects_indeterminate": True,
        "retry_with_same_idempotency_key": True,
        "idempotency_key": key,
        "error": {
            "code": "upstream_http_redirect",
            "message": "结果尚未核实；请使用完全相同的请求和幂等键重试。",
            "upstream_status_code": status_code,
        },
    }


def test_non_close_submit_redirect_does_not_preserve_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep a 302 submit error terminal; the adjacent close test covers the scoped unknown path."""
    import agomtradepro_mcp.server as server_module

    captured_calls: list[dict[str, Any]] = []

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id: int) -> dict[str, Any]:
            return {
                "id": account_id,
                "name": "Alpha Sim",
                "status": "active",
                "account_type": "simulated",
                "total_value": 1050000.0,
                "available_cash": 250000.0,
            }

        @staticmethod
        def get_positions(
            account_id: int,
            asset_code: str | None = None,
        ) -> list[dict[str, Any]]:
            return [
                {
                    "asset_code": asset_code,
                    "quantity": 1200,
                    "available_quantity": 800,
                    "avg_cost": 3.82,
                }
            ]

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    def submit_redirect(**kwargs: Any) -> dict[str, Any]:
        captured_calls.append(dict(kwargs))
        raise sdk_exceptions.AgomTradeProAPIError(
            message="Redirect status 302 rejected",
            status_code=302,
        )

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())
    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "execute_simulated_trade",
        submit_redirect,
    )
    dispatcher = server_module.CORE_DISPATCHER
    arguments = {
        "account_id": 7,
        "asset_code": "510300.SH",
        "side": "BUY",
        "quantity": 1500,
        "price": 4.05,
        "idempotency_key": "submit-redirect-scope-key",
        "asset_type": "fund",
    }

    staged = dispatcher.call(
        capability_key="trading.submit.simulated_order",
        arguments=arguments,
    )
    assert staged["status"] == "confirmation_required"
    token = staged["confirmation_token"]

    rejected = dispatcher.resume_confirmation(confirmation_token=token, approve=True)
    assert rejected["status"] == "error"
    assert rejected["error"]["code"] == "capability_execution_failed"
    assert rejected["error"]["upstream_status_code"] == 302
    assert rejected.get("effects_indeterminate") is not True
    assert "retry_with_same_idempotency_key" not in rejected
    assert len(captured_calls) == 1
    assert captured_calls[0]["idempotency_key"] == arguments["idempotency_key"]
    assert captured_calls[0]["side"] == "buy"

    expired = dispatcher.resume_confirmation(confirmation_token=token, approve=True)
    assert expired["status"] == "error"
    assert expired["error"]["code"] == "confirmation_not_found"


def test_close_structured_unknown_result_keeps_confirmation_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro_mcp.server as server_module

    preview_calls: list[dict[str, Any]] = []
    commit_calls: list[dict[str, Any]] = []
    attempts = 0
    upstream_response = {
        "success": False,
        "error": "平仓结果暂无法确认，请使用相同请求和幂等键重试。",
        "code": "SIMULATED_TRADE_EXECUTION_READBACK_UNKNOWN",
        "effects_indeterminate": True,
        "request_id": "req-structured-close-1",
    }

    class _FakeSimulatedTradingModule:
        @staticmethod
        def get_account(account_id: int) -> dict[str, Any]:
            preview_calls.append({"kind": "account", "account_id": account_id})
            return {"id": account_id, "name": "Alpha Sim", "status": "active"}

        @staticmethod
        def get_positions(account_id: int, asset_code: str | None = None) -> list[dict[str, Any]]:
            preview_calls.append(
                {"kind": "positions", "account_id": account_id, "asset_code": asset_code}
            )
            return [{"asset_code": asset_code, "available_quantity": 500}]

    class _FakeClient:
        simulated_trading = _FakeSimulatedTradingModule()

    def structured_close(**kwargs: Any) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        commit_calls.append(dict(kwargs))
        if attempts == 1:
            return {
                "success": False,
                "status": "unknown",
                "effects_indeterminate": True,
                "retry_with_same_idempotency_key": True,
                "idempotency_key": "unrelated-source-key",
                "error": {"code": "transport_timeout", "message": "结果未知。"},
                "upstream_response": upstream_response,
            }
        return _close_success_response(
            account_id=kwargs["account_id"],
            asset_code=kwargs["asset_code"],
            close_shares=kwargs["close_shares"],
            close_price=kwargs["close_price"],
            idempotency_key=kwargs["idempotency_key"],
            trade_id=7012,
            replayed=True,
        )

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())
    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "close_simulated_position",
        structured_close,
    )
    request_arguments = {
        "account_id": 7,
        "asset_code": "510300.SH",
        "close_shares": 250,
        "close_price": "4.1200",
        "idempotency_key": "close-structured-unknown-1",
    }
    staged = server_module.CORE_DISPATCHER.call(
        capability_key="trading.close.simulated_position",
        arguments=request_arguments,
    )
    token = staged["confirmation_token"]

    unknown = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=token,
        approve=True,
    )
    assert unknown["ok"] is False
    assert unknown["status"] == "unknown"
    assert unknown["confirmation_token"] == token
    assert unknown["idempotency_key"] == request_arguments["idempotency_key"]
    assert unknown["effects_indeterminate"] is True
    assert unknown["retry_with_same_idempotency_key"] is True
    assert unknown["error"]["upstream_response"] == upstream_response
    assert unknown["error"]["source_idempotency_key_mismatch"] is True
    assert attempts == 1

    reused = server_module.CORE_DISPATCHER.call(
        capability_key="trading.close.simulated_position",
        arguments=request_arguments,
    )
    assert reused["status"] == "confirmation_required"
    assert reused["confirmation_token"] == token
    assert reused["idempotency_reused"] is True
    assert len(preview_calls) == 2
    assert attempts == 1

    completed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=token,
        approve=True,
    )
    assert completed["status"] == "completed"
    assert completed["result"]["trade"]["trade_id"] == 7012
    assert completed["result"]["receipt"]["idempotency_key"] == request_arguments["idempotency_key"]
    assert completed["result"]["replayed"] is True
    assert attempts == 2
    assert commit_calls == [request_arguments, request_arguments]
