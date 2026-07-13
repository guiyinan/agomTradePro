# ruff: noqa: F403, F405
"""Core-only read matrix for rotation."""

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
            "rotation.read.regime_catalog",
            "list_rotation_regimes",
            ("list_rotation_regimes",),
            {},
            {
                "regimes": [{"key": "Recovery", "label": "Recovery"}],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "Recovery",
        ),
        (
            "rotation.read.template_catalog",
            "list_rotation_templates",
            ("list_rotation_templates",),
            {},
            {
                "templates": [{"id": 1, "key": "moderate", "name": "稳健型"}],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "moderate",
        ),
        (
            "rotation.read.config_detail",
            "rotation_read_config_detail",
            ("get_rotation_config",),
            {"config_name": "动量轮动策略"},
            {
                "success": True,
                "config": {
                    "id": 3,
                    "name": "动量轮动策略",
                    "strategy_type": "momentum",
                },
                "available_configs": ["动量轮动策略"],
                "error": None,
                "source": "core-only-fallback",
            },
            "momentum",
        ),
        (
            "rotation.read.account_config_list",
            "list_account_rotation_configs",
            ("list_account_rotation_configs",),
            {},
            {
                "configs": [
                    {
                        "id": 2,
                        "account": 308,
                        "risk_tolerance": "moderate",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "308",
        ),
        (
            "rotation.read.account_config_detail",
            "get_account_rotation_config",
            ("get_account_rotation_config",),
            {"account_id": 308},
            {
                "id": 2,
                "account": 308,
                "risk_tolerance": "moderate",
                "regime_allocations": {},
                "is_enabled": True,
                "source": "core-only-fallback",
            },
            "moderate",
        ),
        (
            "rotation.read.asset_catalog",
            "list_rotation_asset_master",
            ("list_rotation_asset_master",),
            {},
            {
                "assets": [
                    {
                        "id": 1,
                        "code": "510300",
                        "name": "沪深300ETF",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "510300",
        ),
        (
            "rotation.read.asset_detail",
            "get_rotation_asset",
            ("get_rotation_asset",),
            {"asset_code": "510300"},
            {
                "id": 1,
                "code": "510300",
                "name": "沪深300ETF",
                "category": "equity",
                "currency": "CNY",
                "is_active": True,
                "source": "core-only-fallback",
            },
            "沪深300ETF",
        ),
        (
            "rotation.read.latest_signal_list",
            "get_latest_rotation_signals",
            ("get_latest_rotation_signals",),
            {},
            {
                "signals": [
                    {
                        "id": 5,
                        "config_name": "动量轮动",
                        "action_required": "rebalance",
                        "actionable": True,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "rebalance",
        ),
        (
            "rotation.compute.asset_comparison",
            "rotation_compute_asset_comparison",
            ("compare_assets",),
            {
                "asset_codes": ["510300", "511260"],
            },
            {
                "calc_date": "2026-07-11",
                "assets": {
                    "510300": {
                        "composite_score": 0.12,
                        "ma_signal": "bullish",
                    },
                    "511260": {
                        "composite_score": -0.03,
                        "ma_signal": "neutral",
                    },
                },
                "source": "core-only-fallback",
            },
            "bullish",
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
