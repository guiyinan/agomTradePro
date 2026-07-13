# ruff: noqa: F403, F405
"""Core-only read matrix for equity."""

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
            "equity.read.pool_catalog",
            "equity_read_pool_catalog",
            ("list_stocks", "get_sector_stocks"),
            {
                "sector": "银行",
                "min_score": 60,
                "limit": 20,
            },
            {
                "success": True,
                "regime": "Recovery",
                "update_time": "2026-07-11",
                "avg_roe": 12.5,
                "avg_pe": 18.0,
                "stocks": [
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "sector": "银行",
                        "score": 70,
                    }
                ],
                "total_count": 1,
                "query": {
                    "sector": "银行",
                    "min_score": 60,
                    "max_score": None,
                    "limit": 20,
                },
                "source": "core-only-fallback",
            },
            "000001.SZ",
        ),
        (
            "equity.read.valuation_analysis",
            "equity_read_valuation_analysis",
            ("get_stock_valuation",),
            {
                "stock_code": "000001.SZ",
                "lookback_days": 365,
            },
            {
                "success": True,
                "stock_code": "000001.SZ",
                "stock_name": "平安银行",
                "sector": "银行",
                "market": "SZ",
                "list_date": "1991-04-03",
                "current_pe": 5.2,
                "pe_percentile": 0.15,
                "current_pb": 0.55,
                "pb_percentile": 0.2,
                "is_undervalued": True,
                "latest_valuation": {"pe": 5.2},
                "financial_data": {"roe": 10.5},
                "source": "core-only-fallback",
            },
            "pe_percentile",
        ),
        (
            "equity.read.valuation_repair_list",
            "equity_read_valuation_repair_list",
            ("list_valuation_repairs",),
            {
                "universe": "all_active",
                "phase": "repairing",
                "limit": 20,
            },
            {
                "universe": "all_active",
                "repairs": [
                    {
                        "stock_code": "000001.SZ",
                        "phase": "repairing",
                        "repair_progress": 0.45,
                    }
                ],
                "total_count": 1,
                "query": {
                    "phase": "repairing",
                    "limit": 20,
                },
                "source": "core-only-fallback",
            },
            "000001.SZ",
        ),
        (
            "equity.read.valuation_freshness",
            "equity_read_valuation_freshness",
            ("get_valuation_data_freshness",),
            {},
            {
                "latest_trade_date": "2026-07-10",
                "lag_days": 0,
                "freshness_status": "fresh",
                "coverage_ratio": 0.99,
                "is_gate_passed": True,
                "source": "core-only-fallback",
            },
            "fresh",
        ),
        (
            "equity.read.valuation_quality_latest",
            "equity_read_valuation_quality_latest",
            ("get_valuation_data_quality_latest",),
            {},
            {
                "as_of_date": "2026-07-10",
                "coverage_ratio": 0.99,
                "valid_ratio": 0.98,
                "primary_source": "akshare",
                "is_gate_passed": True,
                "source": "core-only-fallback",
            },
            "akshare",
        ),
        (
            "equity.compute.valuation_repair_status",
            "equity_compute_valuation_repair_status",
            ("get_valuation_repair_status",),
            {"stock_code": "000001.SZ", "lookback_days": 756},
            {
                "stock_code": "000001.SZ",
                "stock_name": "平安银行",
                "as_of_date": "2026-07-10",
                "phase": "repairing",
                "signal": "hold",
                "composite_percentile": 0.3,
                "repair_progress": 0.4,
                "repair_speed_per_30d": 0.05,
                "estimated_days_to_target": 60,
                "is_stalled": False,
                "confidence": 0.8,
                "data_quality_flag": "ok",
                "data_source_provider": "local_db",
                "data_as_of_date": "2026-07-10",
                "source": "core-only-fallback",
            },
            "repair_progress",
        ),
        (
            "equity.compute.valuation_repair_history",
            "equity_compute_valuation_repair_history",
            ("get_valuation_repair_history",),
            {"stock_code": "000001.SZ", "lookback_days": 252},
            {
                "stock_code": "000001.SZ",
                "points": [
                    {
                        "trade_date": "2026-07-10",
                        "pe_percentile": 0.2,
                        "pb_percentile": 0.4,
                        "composite_percentile": 0.3,
                        "composite_method": "pe_pb_blend",
                    }
                ],
                "data_quality_flag": "ok",
                "data_source_provider": "local_db",
                "data_as_of_date": "2026-07-10",
                "source": "core-only-fallback",
            },
            "composite_method",
        ),
        (
            "equity.read.valuation_repair_config",
            "equity_read_valuation_repair_config",
            ("get_valuation_repair_config",),
            {},
            {
                "config": {
                    "version": 0,
                    "is_active": False,
                    "target_percentile": 0.5,
                },
                "source": "core-only-fallback",
            },
            "target_percentile",
        ),
        (
            "equity.read.valuation_repair_config_catalog",
            "equity_read_valuation_repair_config_catalog",
            ("list_valuation_repair_configs",),
            {"limit": 20},
            {
                "configs": [
                    {
                        "id": 7,
                        "version": 3,
                        "is_active": True,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "version",
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
