"""Focused execution tests for Factor legacy MCP tools."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self) -> None:
        self.factor = SimpleNamespace(
            get_top_stocks=lambda factor_preferences, top_n: {
                "total_stocks": 1,
                "stocks": [
                    {
                        "stock_code": "600000.SH",
                        "factor_preferences": factor_preferences,
                        "top_n": top_n,
                    }
                ],
            },
            explain_stock=lambda stock_code, factor_weights: {
                "stock_code": stock_code,
                "stock_name": "浦发银行",
                "composite_score": 82.5,
                "percentile_rank": 0.0,
                "factor_breakdown": {
                    "roe": {
                        "score": 90.0,
                        "weight": factor_weights.get("roe", 0.0),
                    }
                },
                "category_breakdown": {"quality": 90.0},
            },
        )


def test_factor_top_stocks_executes_through_legacy_raw_tool(
    monkeypatch: pytest.MonkeyPatch,
    legacy_enabled_mcp_server,
) -> None:
    module = importlib.import_module("agomtradepro_mcp.tools.factor_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "get_factor_top_stocks",
            {
                "value_preference": "high",
                "quality_preference": "medium",
                "growth_preference": "low",
                "momentum_preference": "high",
                "top_n": 10,
            },
        )
    )

    rendered = str(result)
    assert "600000.SH" in rendered
    assert "high" in rendered
    assert "low" in rendered
    assert "10" in rendered


def test_factor_stock_explanation_executes_through_legacy_raw_tool(
    monkeypatch: pytest.MonkeyPatch,
    legacy_enabled_mcp_server,
) -> None:
    module = importlib.import_module("agomtradepro_mcp.tools.factor_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "explain_factor_stock",
            {
                "stock_code": "600000.SH",
                "focus": "quality",
            },
        )
    )

    rendered = str(result)
    assert "600000.SH" in rendered
    assert "浦发银行" in rendered
    assert "82.5" in rendered
    assert "0.3" in rendered
