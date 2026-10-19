"""Keep one caller-owned auto-run key intact across MCP SDK boundaries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest


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
