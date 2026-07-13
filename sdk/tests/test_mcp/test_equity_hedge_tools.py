"""Focused execution tests for governed Equity and Hedge legacy replacements."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self) -> None:
        self.equity = SimpleNamespace(
            list_stocks=lambda sector=None, min_score=None, limit=50: [
                {
                    "code": "600000.SH",
                    "sector": sector,
                    "score": min_score,
                    "limit": limit,
                }
            ],
            get_valuation=lambda stock_code, lookback_days=252: {
                "success": True,
                "stock_code": stock_code,
                "stock_name": "平安银行",
                "lookback_days": lookback_days,
                "latest_valuation": {"pe": 5.2},
            },
            get_valuation_repair_status=lambda stock_code, lookback_days=756: {
                "stock_code": stock_code,
                "lookback_days": lookback_days,
                "phase": "repairing",
            },
            get_valuation_repair_history=lambda stock_code, lookback_days=252: [
                {
                    "stock_code": stock_code,
                    "lookback_days": lookback_days,
                    "trade_date": "2026-07-10",
                    "composite_percentile": 0.3,
                }
            ],
            get_valuation_repair_config=lambda: {
                "version": 0,
                "target_percentile": 0.5,
            },
            list_valuation_repair_configs=lambda limit=20: [
                {
                    "id": 7,
                    "version": 3,
                    "limit": limit,
                }
            ],
            create_valuation_repair_config=lambda **kwargs: {
                "id": 8,
                "version": 4,
                "is_active": False,
                **kwargs,
            },
            activate_valuation_repair_config=lambda config_id: {
                "success": True,
                "data": {"id": config_id, "version": 4, "is_active": True},
            },
            rollback_valuation_repair_config=lambda config_id: {
                "success": True,
                "data": {"id": config_id, "version": 2, "is_active": True},
            },
        )
        self.hedge = SimpleNamespace(
            get_correlation_matrix=lambda asset_codes, window_days: {
                "calc_date": "2026-07-11",
                "asset_codes": asset_codes,
                "window_days": window_days,
                "correlation_matrix": {
                    asset_codes[0]: {
                        asset_codes[0]: 1.0,
                        asset_codes[1]: -0.25,
                    },
                    asset_codes[1]: {
                        asset_codes[0]: -0.25,
                        asset_codes[1]: 1.0,
                    },
                },
            },
        )


@pytest.fixture
def patched_client(monkeypatch: pytest.MonkeyPatch) -> None:
    for module_name in (
        "agomtradepro_mcp.tools.equity_tools",
        "agomtradepro_mcp.tools.hedge_tools",
    ):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)


def test_list_stocks_executes_through_legacy_raw_tool(
    legacy_enabled_mcp_server,
    patched_client: None,
) -> None:
    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "list_stocks",
            {
                "sector": "银行",
                "min_score": 70.0,
                "limit": 12,
            },
        )
    )

    rendered = str(result)
    assert "600000.SH" in rendered
    assert "银行" in rendered
    assert "70.0" in rendered
    assert "12" in rendered


def test_stock_valuation_executes_through_legacy_raw_tool(
    legacy_enabled_mcp_server,
    patched_client: None,
) -> None:
    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "get_stock_valuation",
            {
                "stock_code": "000001.SZ",
                "lookback_days": 365,
            },
        )
    )

    rendered = str(result)
    assert "000001.SZ" in rendered
    assert "365" in rendered
    assert "5.2" in rendered


@pytest.mark.parametrize(
    ("tool_name", "arguments", "marker"),
    [
        (
            "get_valuation_repair_status",
            {"stock_code": "000001.SZ", "lookback_days": 756},
            "repairing",
        ),
        (
            "get_valuation_repair_history",
            {"stock_code": "000001.SZ", "lookback_days": 252},
            "composite_percentile",
        ),
        ("get_valuation_repair_config", {}, "target_percentile"),
        ("list_valuation_repair_configs", {"limit": 20}, "version"),
    ],
)
def test_equity_valuation_repair_reads_execute_through_legacy_raw_tools(
    legacy_enabled_mcp_server,
    patched_client: None,
    tool_name: str,
    arguments: dict,
    marker: str,
) -> None:
    result = asyncio.run(legacy_enabled_mcp_server.call_tool(tool_name, arguments))

    rendered = str(result)
    assert "000001.SZ" in rendered or tool_name.endswith("config") or "configs" in tool_name
    assert marker in rendered


def test_create_valuation_repair_config_executes_through_legacy_raw_tool(
    legacy_enabled_mcp_server,
    patched_client: None,
) -> None:
    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "create_valuation_repair_config",
            {
                "change_reason": "Governed raw compatibility proof.",
                "target_percentile": 0.55,
            },
        )
    )

    rendered = str(result)
    assert "Governed raw compatibility proof." in rendered
    assert "0.55" in rendered
    assert "is_active" in rendered


@pytest.mark.parametrize(
    "tool_name",
    (
        "activate_valuation_repair_config",
        "rollback_valuation_repair_config",
    ),
)
def test_valuation_repair_config_activation_aliases_execute_through_raw_tools(
    legacy_enabled_mcp_server,
    patched_client: None,
    tool_name: str,
) -> None:
    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            tool_name,
            {"config_id": 8},
        )
    )

    rendered = str(result)
    assert "is_active" in rendered
    assert "True" in rendered or "true" in rendered


def test_hedge_correlation_matrix_executes_through_legacy_raw_tool(
    legacy_enabled_mcp_server,
    patched_client: None,
) -> None:
    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "get_hedge_correlation_matrix",
            {
                "asset_codes": ["510300", "511260"],
                "window_days": 90,
            },
        )
    )

    rendered = str(result)
    assert "2026-07-11" in rendered
    assert "510300" in rendered
    assert "511260" in rendered
    assert "-0.25" in rendered
    assert "90" in rendered
