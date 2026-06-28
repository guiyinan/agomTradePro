import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self):
        self.risk_center = SimpleNamespace(
            get_floor=lambda: {"max_total_position_pct": 0.8},
            update_floor=lambda payload: {"updated": payload},
            list_templates=lambda: [{"key": "moderate"}],
            upsert_account_policy=lambda payload: {"policy": payload},
            get_account_policy=lambda account_id: {"account_id": account_id},
            get_effective_policy=lambda account_id: {
                "account_id": account_id,
                "parameters": {"max_total_position_pct": 0.8},
            },
            list_exceptions=lambda account_id=None: [{"account_id": account_id}],
            create_exception=lambda payload: {"exception": payload},
            check_pre_trade=lambda payload: {"passed": True, "payload": payload},
            check_post_investment=lambda payload: {"status": "ok", "payload": payload},
            generate_daily_report=lambda payload: {"risk_daily_report": {"status": "ok"}, "payload": payload},
            get_daily_report=lambda account_id, report_date: {
                "account_id": account_id,
                "report_date": report_date,
            },
            list_daily_reports=lambda **kwargs: [{"query": kwargs}],
        )


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("get_risk_floor", {}),
        ("update_risk_floor", {"payload": {"max_total_position_pct": 0.75, "reason": "test"}}),
        ("list_risk_templates", {}),
        ("upsert_account_risk_policy", {"payload": {"account_id": 1, "max_total_position_pct": 0.7}}),
        ("get_account_risk_policy", {"account_id": 1}),
        ("get_effective_risk_policy", {"account_id": 1}),
        ("list_risk_exceptions", {"account_id": 1}),
        (
            "create_risk_exception",
            {
                "payload": {
                    "account_id": 1,
                    "field_name": "max_total_position_pct",
                    "allowed_value": 0.9,
                    "reason": "temporary test",
                    "expires_at": "2026-06-28T00:00:00Z",
                }
            },
        ),
        (
            "check_pre_trade_risk",
            {
                "account_id": 1,
                "symbol": "000001.SZ",
                "side": "buy",
                "quantity": 100,
                "price": 10.0,
                "account_equity": 100000.0,
                "total_position_value": 50000.0,
                "cash_balance": 50000.0,
            },
        ),
        (
            "check_post_investment_risk",
            {
                "account_id": 1,
                "account_equity": 100000.0,
                "cash_balance": 20000.0,
                "positions": [
                    {
                        "symbol": "000001.SZ",
                        "market_value": 30000.0,
                        "unrealized_pnl_pct": -0.05,
                    }
                ],
            },
        ),
        (
            "generate_risk_center_daily_report",
            {
                "account_id": 1,
                "report_date": "2026-06-28",
                "account_equity": 100000.0,
                "positions": [],
            },
        ),
        ("get_risk_center_daily_report", {"account_id": 1, "report_date": "2026-06-28"}),
        (
            "list_risk_center_daily_reports",
            {
                "account_id": 1,
                "start_date": "2026-06-01",
                "end_date": "2026-06-28",
                "limit": 30,
            },
        ),
    ],
)
def test_risk_center_tools_can_execute(monkeypatch: pytest.MonkeyPatch, tool_name: str, arguments: dict):
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    module = importlib.import_module("agomtradepro_mcp.tools.risk_center_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result is not None
