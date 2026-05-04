import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self):
        self.fund = SimpleNamespace(
            get_fund_score=lambda fund_code, as_of_date=None: {
                "fund_code": fund_code,
                "as_of_date": str(as_of_date) if as_of_date else None,
            },
            rank_funds=lambda regime="Recovery", max_count=50: [
                {"regime": regime, "max_count": max_count, "fund_code": "000001"}
            ],
            screen_funds=(
                lambda regime=None, custom_types=None, custom_styles=None, min_scale=None, limit=30: {
                    "success": True,
                    "regime": regime or "Recovery",
                    "fund_codes": ["000001"],
                    "fund_names": ["华夏成长"],
                    "screening_criteria": {
                        "custom_types": custom_types,
                        "custom_styles": custom_styles,
                        "min_scale": min_scale,
                        "limit": limit,
                    },
                }
            ),
            list_funds=lambda fund_type=None, min_score=None, limit=50: [
                {"fund_type": fund_type, "min_score": min_score, "limit": limit}
            ],
            get_fund_detail=lambda fund_code: {
                "fund_code": fund_code,
                "fund_name": "华夏成长",
                "fund_type": "股票型",
            },
            get_recommendations=lambda regime=None, fund_type=None, limit=20: [
                {"regime": regime, "fund_type": fund_type, "limit": limit}
            ],
            analyze_fund=lambda fund_code, report_date=None, as_of_date=None: {
                "fund_code": fund_code,
                "report_date": str(report_date) if report_date else None,
                "as_of_date": str(as_of_date) if as_of_date else None,
            },
            get_nav_history=lambda fund_code, start_date=None, end_date=None, limit=100: [
                {
                    "fund_code": fund_code,
                    "start_date": str(start_date) if start_date else None,
                    "end_date": str(end_date) if end_date else None,
                    "limit": limit,
                }
            ],
            get_performance=lambda fund_code, period="1y": {
                "fund_code": fund_code,
                "period": period,
            },
            get_holdings=lambda fund_code, report_date=None, as_of_date=None: [
                {
                    "fund_code": fund_code,
                    "report_date": str(report_date) if report_date else None,
                    "as_of_date": str(as_of_date) if as_of_date else None,
                }
            ],
        )


@pytest.mark.parametrize(
    "tool_name,arguments,expected_snippet",
    [
        ("rank_funds", {"regime": "Recovery", "max_count": 5}, "000001"),
        (
            "screen_funds",
            {
                "regime": "Recovery",
                "custom_types": ["股票型"],
                "custom_styles": ["成长"],
                "min_scale": 1000000000,
                "limit": 10,
            },
            "华夏成长",
        ),
        ("get_fund_detail", {"fund_code": "000001.OF"}, "华夏成长"),
        (
            "get_fund_nav_history",
            {
                "fund_code": "000001.OF",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "limit": 30,
            },
            "2024-12-31",
        ),
        (
            "analyze_fund",
            {"fund_code": "000001.OF", "report_date": "2024-12-31"},
            "2024-12-31",
        ),
        (
            "get_fund_holdings",
            {"fund_code": "000001.OF", "report_date": "2024-09-30"},
            "2024-09-30",
        ),
        ("get_fund_performance", {"fund_code": "000001.OF", "period": "1y"}, "1y"),
        (
            "get_fund_recommendations",
            {"regime": "Recovery", "fund_type": "股票型", "limit": 10},
            "Recovery",
        ),
    ],
)
def test_fund_tools_execute(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict,
    expected_snippet: str,
):
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    module = importlib.import_module("agomtradepro_mcp.tools.fund_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert expected_snippet in str(result)
