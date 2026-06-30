"""Tests for dashboard MCP tools exposing account-driven Alpha flows."""

from unittest.mock import MagicMock, patch

from agomtradepro_mcp.tools.dashboard_tools import register_dashboard_tools
from mcp.server.fastmcp import FastMCP


def test_register_dashboard_alpha_tools() -> None:
    server = FastMCP("test")
    register_dashboard_tools(server)

    tool_names = set(server._tool_manager._tools.keys())

    assert "get_dashboard_alpha_candidates" in tool_names
    assert "get_dashboard_alpha_history" in tool_names
    assert "get_dashboard_alpha_history_detail" in tool_names
    assert "trigger_dashboard_alpha_refresh" in tool_names
    assert "get_auto_advisor_decision_sheet" in tool_names
    assert "get_auto_advisor_console" in tool_names
    assert "ask_auto_advisor" in tool_names
    assert "get_auto_advisor_weekly_report" in tool_names
    assert "list_auto_advisor_weekly_report_history" in tool_names
    assert "list_auto_advisor_notifications" in tool_names


@patch("agomtradepro_mcp.tools.dashboard_tools.AgomTradeProClient")
def test_auto_advisor_mcp_tools_call_sdk(mock_client_cls) -> None:
    mock_client = MagicMock()
    mock_client.decision_rhythm.advisor_sheet.return_value = {
        "today_conclusion": "REVIEW",
        "orders": [],
    }
    mock_client.dashboard.auto_advisor_console.return_value = {
        "account_id": "135",
        "risk_gate": {"status": "pass"},
    }
    mock_client.dashboard.auto_advisor_query.return_value = {
        "answer": "最大风险是集中度。",
        "evidence": [],
    }
    mock_client.dashboard.auto_advisor_weekly_report.return_value = {
        "account_id": "135",
        "investment_diary": {},
    }
    mock_client.dashboard.auto_advisor_weekly_report_history.return_value = {
        "items": [{"id": 1}],
    }
    mock_client.dashboard.auto_advisor_notifications.return_value = {
        "items": [{"id": 2}],
    }
    mock_client_cls.return_value = mock_client

    server = FastMCP("test")
    register_dashboard_tools(server)

    sheet_fn = server._tool_manager._tools["get_auto_advisor_decision_sheet"].fn
    console_fn = server._tool_manager._tools["get_auto_advisor_console"].fn
    query_fn = server._tool_manager._tools["ask_auto_advisor"].fn
    report_fn = server._tool_manager._tools["get_auto_advisor_weekly_report"].fn
    history_fn = server._tool_manager._tools["list_auto_advisor_weekly_report_history"].fn
    notification_fn = server._tool_manager._tools["list_auto_advisor_notifications"].fn

    sheet = sheet_fn(account_id=135)
    console = console_fn(account_id=135)
    answer = query_fn(account_id=135, question="最大风险是什么")
    report = report_fn(account_id=135, as_of="2026-06-30")
    history = history_fn(account_id=135, limit=5)
    notifications = notification_fn(limit=3)

    mock_client.decision_rhythm.advisor_sheet.assert_called_once_with(account_id=135)
    mock_client.dashboard.auto_advisor_console.assert_called_once_with(account_id=135)
    mock_client.dashboard.auto_advisor_query.assert_called_once_with(
        account_id=135,
        question="最大风险是什么",
    )
    mock_client.dashboard.auto_advisor_weekly_report.assert_called_once_with(
        account_id=135,
        as_of="2026-06-30",
    )
    mock_client.dashboard.auto_advisor_weekly_report_history.assert_called_once_with(
        account_id=135,
        limit=5,
    )
    mock_client.dashboard.auto_advisor_notifications.assert_called_once_with(
        account_id=None,
        limit=3,
    )
    assert sheet["today_conclusion"] == "REVIEW"
    assert console["risk_gate"]["status"] == "pass"
    assert answer["answer"] == "最大风险是集中度。"
    assert report["account_id"] == "135"
    assert history["items"][0]["id"] == 1
    assert notifications["items"][0]["id"] == 2


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
    result = tool_fn(top_n=12, portfolio_id=21, pool_mode="market")

    mock_client.dashboard.alpha_stocks.assert_called_once_with(
        top_n=12,
        portfolio_id=21,
        pool_mode="market",
    )
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
    refresh = refresh_fn(top_n=15, portfolio_id=3, pool_mode="price_covered")

    mock_client.dashboard.alpha_history_detail.assert_called_once_with(9)
    mock_client.dashboard.alpha_refresh.assert_called_once_with(
        top_n=15,
        portfolio_id=3,
        pool_mode="price_covered",
    )
    assert detail["data"]["id"] == 9
    assert refresh["task_id"] == "task-123"


@patch("agomtradepro_mcp.tools.dashboard_tools.AgomTradeProClient")
def test_dashboard_alpha_tools_forward_alpha_scope_when_explicit(mock_client_cls) -> None:
    mock_client = MagicMock()
    mock_client.dashboard.alpha_stocks.return_value = {"success": True, "data": {"top_candidates": []}}
    mock_client.dashboard.alpha_refresh.return_value = {"success": True, "task_id": "task-general"}
    mock_client_cls.return_value = mock_client

    server = FastMCP("test")
    register_dashboard_tools(server)

    candidates_fn = server._tool_manager._tools["get_dashboard_alpha_candidates"].fn
    refresh_fn = server._tool_manager._tools["trigger_dashboard_alpha_refresh"].fn

    candidates_fn(top_n=10, alpha_scope="general")
    refresh_fn(top_n=8, portfolio_id=5, pool_mode="price_covered", alpha_scope="portfolio")

    mock_client.dashboard.alpha_stocks.assert_called_once_with(top_n=10, portfolio_id=None, pool_mode=None, alpha_scope="general")
    mock_client.dashboard.alpha_refresh.assert_called_once_with(
        top_n=8,
        portfolio_id=5,
        pool_mode="price_covered",
        alpha_scope="portfolio",
    )
