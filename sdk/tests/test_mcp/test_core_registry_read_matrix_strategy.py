# ruff: noqa: F403, F405
"""Core-only read matrix for strategy."""

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
            "strategy.read.catalog",
            "strategy_read_catalog",
            ("list_strategies",),
            {
                "strategy_type": "rule_based",
                "is_active": True,
                "limit": 10,
            },
            {
                "strategies": [
                    {
                        "id": 4,
                        "name": "Macro Guard",
                        "strategy_type": "rule_based",
                        "is_active": True,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "Macro Guard",
        ),
        (
            "strategy.read.detail",
            "strategy_read_detail",
            ("get_strategy",),
            {"strategy_id": 4},
            {
                "strategy": {
                    "id": 4,
                    "name": "Macro Guard",
                    "strategy_type": "rule_based",
                    "rules_count": 2,
                },
                "source": "core-only-fallback",
            },
            "rules_count",
        ),
        (
            "strategy.read.ai_config_catalog",
            "strategy_read_ai_config_catalog",
            ("list_ai_strategy_configs",),
            {
                "strategy_id": 4,
                "approval_mode": "conditional",
                "limit": 10,
            },
            {
                "configs": [
                    {
                        "id": 8,
                        "strategy": 4,
                        "approval_mode": "conditional",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "conditional",
        ),
        (
            "strategy.read.ai_config_detail",
            "strategy_read_ai_config_detail",
            ("get_strategy_ai_config",),
            {"strategy_id": 4},
            {
                "strategy_id": 4,
                "exists": True,
                "config": {
                    "id": 8,
                    "strategy": 4,
                    "approval_mode": "conditional",
                },
                "source": "core-only-fallback",
            },
            "exists",
        ),
        (
            "strategy.read.position_rule_catalog",
            "strategy_read_position_rule_catalog",
            ("list_position_rules",),
            {"strategy_id": 4, "is_active": True, "limit": 10},
            {
                "rules": [
                    {
                        "id": 12,
                        "strategy": 4,
                        "name": "ATR Guard",
                        "is_active": True,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "ATR Guard",
        ),
        (
            "strategy.read.position_rule_detail",
            "strategy_read_position_rule_detail",
            ("get_strategy_position_rule",),
            {"strategy_id": 4},
            {
                "strategy_id": 4,
                "rule": {
                    "id": 12,
                    "strategy": 4,
                    "name": "ATR Guard",
                },
                "source": "core-only-fallback",
            },
            "ATR Guard",
        ),
        (
            "strategy.compute.position_rule",
            "strategy_compute_position_rule",
            ("evaluate_position_rule",),
            {
                "rule_id": 12,
                "context": {
                    "current_price": 10.0,
                    "account_equity": 100000.0,
                },
            },
            {
                "should_buy": True,
                "should_sell": False,
                "buy_price": 10.0,
                "sell_price": 12.0,
                "stop_loss_price": 9.0,
                "take_profit_price": 12.0,
                "position_size": 1000.0,
                "risk_reward_ratio": 2.0,
                "source": "core-only-fallback",
            },
            "risk_reward_ratio",
        ),
        (
            "strategy.compute.position_management",
            "strategy_compute_position_management",
            ("evaluate_strategy_position_management",),
            {
                "strategy_id": 4,
                "context": {
                    "current_price": 13.0,
                    "account_equity": 100000.0,
                },
            },
            {
                "should_buy": False,
                "should_sell": True,
                "buy_price": 10.0,
                "sell_price": 12.0,
                "stop_loss_price": 9.0,
                "take_profit_price": 14.0,
                "position_size": 500.0,
                "risk_reward_ratio": 0.5,
                "source": "core-only-fallback",
            },
            "position_size",
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
