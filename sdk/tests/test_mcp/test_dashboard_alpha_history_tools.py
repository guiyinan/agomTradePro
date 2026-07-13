"""Focused raw MCP execution tests for Dashboard Alpha history reads."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self) -> None:
        self.dashboard = SimpleNamespace(
            alpha_history=lambda **kwargs: {
                "success": True,
                "data": [
                    {
                        "id": 7,
                        "portfolio_id": kwargs.get("portfolio_id"),
                        "trade_date": kwargs.get("trade_date"),
                        "stock_code": kwargs.get("stock_code"),
                        "stage": kwargs.get("stage"),
                        "source": kwargs.get("source"),
                    }
                ],
            },
            alpha_history_detail=lambda run_id: {
                "success": True,
                "data": {
                    "id": run_id,
                    "snapshots": [{"code": "000001.SZ", "stage": "actionable"}],
                },
            },
        )


@pytest.fixture
def patched_dashboard_client(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("agomtradepro_mcp.tools.dashboard_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)


def test_dashboard_alpha_history_executes_through_legacy_raw_tool(
    legacy_enabled_mcp_server,
    patched_dashboard_client: None,
) -> None:
    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "get_dashboard_alpha_history",
            {
                "portfolio_id": 135,
                "trade_date": "2026-07-11",
                "stock_code": "000001.SZ",
                "stage": "actionable",
                "source": "cache",
            },
        )
    )

    rendered = str(result)
    assert "get_dashboard_alpha_history" not in rendered
    assert "000001.SZ" in rendered
    assert "actionable" in rendered
    assert "cache" in rendered


def test_dashboard_alpha_history_detail_executes_through_legacy_raw_tool(
    legacy_enabled_mcp_server,
    patched_dashboard_client: None,
) -> None:
    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "get_dashboard_alpha_history_detail",
            {"run_id": 7},
        )
    )

    rendered = str(result)
    assert "000001.SZ" in rendered
    assert "actionable" in rendered
    assert "7" in rendered
