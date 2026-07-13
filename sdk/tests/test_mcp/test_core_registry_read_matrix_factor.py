# ruff: noqa: F403, F405
"""Core-only read matrix for factor."""

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
            "factor.compute.top_stocks",
            "factor_compute_top_stocks",
            ("get_factor_top_stocks",),
            {
                "value_preference": "high",
                "quality_preference": "medium",
                "growth_preference": "low",
                "momentum_preference": "high",
                "top_n": 10,
            },
            {
                "total_stocks": 1,
                "stocks": [
                    {
                        "stock_code": "600000.SH",
                        "composite_score": 88.5,
                    }
                ],
                "source": "core-only-fallback",
            },
            "600000.SH",
        ),
        (
            "factor.compute.stock_explanation",
            "factor_compute_stock_explanation",
            ("explain_factor_stock",),
            {
                "stock_code": "600000.SH",
                "focus": "quality",
            },
            {
                "stock_code": "600000.SH",
                "stock_name": "浦发银行",
                "composite_score": 82.5,
                "percentile_rank": 0.0,
                "factor_breakdown": {
                    "roe": {
                        "score": 90.0,
                        "weight": 0.3,
                        "contribution": 27.0,
                    }
                },
                "category_breakdown": {"quality": 90.0},
                "source": "core-only-fallback",
            },
            "浦发银行",
        ),
        (
            "factor.read.definition_catalog",
            "factor_read_definition_catalog",
            ("list_factor_definitions",),
            {},
            {
                "factors": [
                    {
                        "code": "pe_ttm",
                        "name": "市盈率",
                        "category": "value",
                        "direction": "negative",
                    }
                ],
                "by_category": {
                    "value": [
                        {
                            "code": "pe_ttm",
                            "name": "市盈率",
                            "category": "value",
                            "direction": "negative",
                        }
                    ]
                },
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "pe_ttm",
        ),
        (
            "factor.read.config_catalog",
            "factor_read_config_catalog",
            ("list_factor_configs",),
            {},
            {
                "configs": [
                    {
                        "name": "价值组合",
                        "universe": "all_a",
                        "top_n": 30,
                        "is_active": True,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "价值组合",
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
