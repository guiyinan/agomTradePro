"""Tests for dashboard MCP tools exposing account-driven Alpha flows."""

from unittest.mock import MagicMock, patch

from mcp.server.fastmcp import FastMCP

from agomtradepro_mcp.tools.dashboard_tools import register_dashboard_tools


def test_register_dashboard_alpha_tools() -> None:
    server = FastMCP("test")
    register_dashboard_tools(server)

    tool_names = set(server._tool_manager._tools.keys())

    assert "get_dashboard_alpha_candidates" in tool_names
    assert "get_dashboard_alpha_history" in tool_names
    assert "get_dashboard_alpha_history_detail" in tool_names
    assert "trigger_dashboard_alpha_refresh" in tool_names


@patch("agomtradepro_mcp.tools.dashboard_tools.AgomTradeProClient")
def test_get_dashboard_alpha_candidates_calls_sdk(mock_client_cls) -> None:
    mock_client = MagicMock()
    mock_client.dashboard.alpha_stocks.return_value = {
        "success": True,
        "data": {"top_candidates": [], "pool": {"portfolio_id": 21}},
    }
    mock_client_cls.return_value = mock_client

    server = FastMCP("test")
    register_dashboard_tools(server)

    tool_fn = server._tool_manager._tools["get_dashboard_alpha_candidates"].fn
    result = tool_fn(top_n=12, portfolio_id=21)

    mock_client.dashboard.alpha_stocks.assert_called_once_with(top_n=12, portfolio_id=21)
    assert result["success"] is True


@patch("agomtradepro_mcp.tools.dashboard_tools.AgomTradeProClient")
def test_get_dashboard_alpha_history_calls_sdk(mock_client_cls) -> None:
    mock_client = MagicMock()
    mock_client.dashboard.alpha_history.return_value = {
        "success": True,
        "data": [{"id": 5, "source": "cache"}],
    }
    mock_client_cls.return_value = mock_client

    server = FastMCP("test")
    register_dashboard_tools(server)

    tool_fn = server._tool_manager._tools["get_dashboard_alpha_history"].fn
    result = tool_fn(
        portfolio_id=8,
        trade_date="2026-04-16",
        stock_code="000001.SZ",
        stage="actionable",
        source="cache",
    )

    mock_client.dashboard.alpha_history.assert_called_once_with(
        portfolio_id=8,
        trade_date="2026-04-16",
        stock_code="000001.SZ",
        stage="actionable",
        source="cache",
    )
    assert result["data"][0]["id"] == 5


@patch("agomtradepro_mcp.tools.dashboard_tools.AgomTradeProClient")
def test_dashboard_alpha_history_detail_and_refresh_call_sdk(mock_client_cls) -> None:
    mock_client = MagicMock()
    mock_client.dashboard.alpha_history_detail.return_value = {
        "success": True,
        "data": {"id": 9, "snapshots": []},
    }
    mock_client.dashboard.alpha_refresh.return_value = {
        "success": True,
        "task_id": "task-123",
    }
    mock_client_cls.return_value = mock_client

    server = FastMCP("test")
    register_dashboard_tools(server)

    detail_fn = server._tool_manager._tools["get_dashboard_alpha_history_detail"].fn
    refresh_fn = server._tool_manager._tools["trigger_dashboard_alpha_refresh"].fn

    detail = detail_fn(run_id=9)
    refresh = refresh_fn(top_n=15, portfolio_id=3)

    mock_client.dashboard.alpha_history_detail.assert_called_once_with(9)
    mock_client.dashboard.alpha_refresh.assert_called_once_with(top_n=15, portfolio_id=3)
    assert detail["data"]["id"] == 9
    assert refresh["task_id"] == "task-123"
