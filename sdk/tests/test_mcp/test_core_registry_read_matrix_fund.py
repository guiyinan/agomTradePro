# ruff: noqa: F403, F405
"""Core-only read matrix for fund."""

from .core_registry_support import *


@pytest.mark.parametrize(
    (
        "capability_key",
        "executor_ref",
        "legacy_tool_names",
        "arguments",
        "payload",
        "expected",
    ),
    [
        (
            "fund.read.ranking",
            "rank_funds",
            ("rank_funds",),
            {"regime": "Recovery", "max_count": 20},
            {
                "regime": "Recovery",
                "funds": [
                    {
                        "fund_code": "000001",
                        "fund_name": "华夏成长",
                        "total_score": 85.5,
                        "rank": 1,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "85.5",
        ),
        (
            "fund.read.detail",
            "get_fund_detail",
            ("get_fund_detail",),
            {"fund_code": "000001.OF"},
            {
                "fund_code": "000001",
                "fund_name": "华夏成长",
                "fund_type": "股票型",
                "investment_style": "成长",
                "source": "core-only-fallback",
            },
            "股票型",
        ),
        (
            "fund.read.nav_history",
            "get_fund_nav_history",
            ("get_fund_nav_history",),
            {
                "fund_code": "000001.OF",
                "start_date": "2026-07-01",
                "end_date": "2026-07-10",
            },
            {
                "fund_code": "000001",
                "nav_data": [
                    {
                        "fund_code": "000001",
                        "nav_date": "2026-07-09",
                        "unit_nav": "1.2345",
                    }
                ],
                "total_count": 1,
                "query": {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-10",
                },
                "source": "core-only-fallback",
            },
            "1.2345",
        ),
        (
            "fund.read.holdings",
            "get_fund_holdings",
            ("get_fund_holdings",),
            {
                "fund_code": "000001.OF",
                "report_date": "2026-06-30",
            },
            {
                "fund_code": "000001",
                "report_date": "2026-06-30",
                "holdings": [
                    {
                        "stock_code": "600519.SH",
                        "stock_name": "贵州茅台",
                        "holding_ratio": 8.75,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "600519.SH",
        ),
    ],
)
def test_agom_capability_call_reads_data_family_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    capability_key,
    executor_ref,
    legacy_tool_names,
    arguments,
    payload,
    expected,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        executor_ref,
        lambda **kwargs: payload,
    )
    assert all(legacy_tool_names)

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": capability_key,
                "arguments": arguments,
            },
        )
    )

    rendered = str(result)
    assert capability_key in rendered
    assert expected in rendered
    assert "core-only-fallback" in rendered
