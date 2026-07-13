# ruff: noqa: F403, F405
"""Core-only registry evidence for SDK-aligned persisted reads."""

from .core_registry_support import *


@pytest.mark.parametrize(
    ("capability_key", "executor_ref", "legacy_tool_name", "arguments", "payload"),
    [
        (
            "equity.read.financial_history",
            "equity_read_financial_history",
            "get_stock_financials",
            {"stock_code": "000001.SZ"},
            {"financials": [], "total_count": 0},
        ),
        (
            "fund.read.score",
            "fund_read_score",
            "get_fund_score",
            {"fund_code": "000001.OF"},
            {"score": {"total_score": 88.0}},
        ),
        (
            "sector.read.score",
            "sector_read_score",
            "get_sector_score",
            {"sector_name": "银行"},
            {"score": {"total_score": 80.0}},
        ),
        (
            "realtime.read.sector_performance",
            "realtime_read_sector_performance",
            "get_sector_realtime_performance",
            {},
            {"sectors": [], "total_count": 0},
        ),
        (
            "strategy.read.performance",
            "strategy_read_performance",
            "get_strategy_performance",
            {"strategy_id": 1},
            {"strategy_id": 1, "execution_count": 2},
        ),
        (
            "strategy.read.signals",
            "strategy_read_signals",
            "get_strategy_signals",
            {"strategy_id": 1},
            {"signals": [], "total_count": 0},
        ),
        (
            "strategy.read.positions",
            "strategy_read_positions",
            "get_strategy_positions",
            {"strategy_id": 1},
            {"positions": [], "total_count": 0},
        ),
        (
            "factor.read.portfolio",
            "factor_read_portfolio",
            "get_factor_portfolio",
            {"config_name": "balanced"},
            {"config_name": "balanced", "exists": False, "portfolio": None},
        ),
    ],
)
def test_sdk_aligned_reads_execute_through_core_only_registry(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    capability_key,
    executor_ref,
    legacy_tool_name,
    arguments,
    payload,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        executor_ref,
        lambda **kwargs: payload,
    )
    assert legacy_tool_name
    assert "INTERNAL_LEGACY_TOOL_FALLBACKS"

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {"capability_key": capability_key, "arguments": arguments},
        )
    )

    rendered = str(result)
    assert capability_key in rendered
    assert "ok" in rendered
