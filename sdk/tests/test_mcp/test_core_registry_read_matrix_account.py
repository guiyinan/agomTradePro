# ruff: noqa: F403, F405
"""Core-only read matrix for account."""

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
            "account.read.macro_sizing_config",
            "get_macro_sizing_config",
            ("get_macro_sizing_config",),
            {},
            {
                "version": 4,
                "is_active": True,
                "warning_factor": 0.45,
                "source": "core-only-fallback",
            },
            "warning_factor",
        ),
        (
            "account.read.positions",
            "get_positions",
            ("get_positions",),
            {"portfolio_id": 7, "asset_code": "510300.SH", "limit": 20},
            {
                "positions": [
                    {
                        "asset_code": "510300.SH",
                        "quantity": 200.0,
                        "market_value": 782.0,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "510300.SH",
        ),
        (
            "account.read.portfolio_catalog",
            "account_read_portfolio_catalog",
            ("list_portfolios",),
            {"limit": 25},
            {
                "portfolios": [{"id": 7, "name": "Core"}],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "Core",
        ),
        (
            "account.read.portfolio_detail",
            "account_read_portfolio_detail",
            ("get_portfolio",),
            {"portfolio_id": 7},
            {
                "portfolio": {"id": 7, "name": "Core"},
                "positions": [{"id": 11, "asset_code": "510300.SH"}],
                "source": "core-only-fallback",
            },
            "510300.SH",
        ),
        (
            "account.read.position_records",
            "account_read_position_records",
            ("get_positions_detailed", "export_positions_json"),
            {"portfolio_id": 7, "include_closed": True, "limit": 20},
            {
                "positions": [{"id": 11, "asset_code": "510300.SH"}],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "510300.SH",
        ),
        (
            "account.read.transaction_records",
            "account_read_transaction_records",
            ("get_transactions_detailed", "export_transactions_json"),
            {"portfolio_id": 7, "limit": 30},
            {
                "transactions": [{"id": 21, "asset_code": "510300.SH"}],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "510300.SH",
        ),
        (
            "account.read.capital_flow_records",
            "account_read_capital_flow_records",
            ("get_capital_flows_detailed", "export_capital_flows_json"),
            {"portfolio_id": 7, "limit": 40},
            {
                "capital_flows": [{"id": 31, "flow_type": "deposit"}],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "deposit",
        ),
        (
            "account.read.portfolio_statistics",
            "get_portfolio_statistics",
            ("get_portfolio_statistics",),
            {"portfolio_id": 7},
            {
                "total_value": 100000.0,
                "position_count": 3,
                "net_capital_flow": 50000.0,
                "source": "core-only-fallback",
            },
            "net_capital_flow",
        ),
        (
            "account.read.trading_cost_configs",
            "get_trading_cost_configs",
            ("get_trading_cost_configs",),
            {"portfolio_id": 7, "limit": 25},
            {
                "portfolio_id": 7,
                "configs": [{"id": 11, "portfolio": 7}],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "configs",
        ),
        (
            "account.calculate.trading_cost",
            "calculate_trading_cost",
            ("calculate_trading_cost",),
            {
                "config_id": 11,
                "action": "sell",
                "amount": 10000.0,
                "is_shanghai": True,
            },
            {
                "commission": 5.0,
                "stamp_duty": 10.0,
                "transfer_fee": 0.2,
                "total": 15.2,
                "source": "core-only-fallback",
            },
            "15.2",
        ),
        (
            "account.read.account_list",
            "account_read_account_list",
            ("list_accounts", "list_simulated_accounts"),
            {"active_only": True, "account_type": "simulated"},
            {
                "accounts": [
                    {
                        "account_id": 7,
                        "account_name": "研究模拟账户",
                        "account_type": "simulated",
                    }
                ],
                "total_count": 1,
                "query": {
                    "active_only": True,
                    "account_type": "simulated",
                },
                "source": "core-only-fallback",
            },
            "研究模拟账户",
        ),
        (
            "account.read.account_detail",
            "account_read_account_detail",
            ("get_account", "get_simulated_account"),
            {"account_id": 7},
            {
                "account_id": 7,
                "account": {
                    "account_id": 7,
                    "account_name": "研究模拟账户",
                    "account_type": "simulated",
                },
                "source": "core-only-fallback",
            },
            "account_name",
        ),
        (
            "account.read.account_positions",
            "account_read_account_positions",
            ("get_account_positions", "get_simulated_positions"),
            {"account_id": 7},
            {
                "account_id": 7,
                "positions": [
                    {
                        "asset_code": "510300.SH",
                        "quantity": 200,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "510300.SH",
        ),
        (
            "account.read.account_performance",
            "account_read_account_performance",
            ("get_account_performance", "get_simulated_performance"),
            {
                "account_id": 7,
                "start_date": "2026-07-01",
                "end_date": "2026-07-10",
            },
            {
                "account_id": 7,
                "mode": "date_range",
                "query": {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-10",
                },
                "performance": {
                    "returns": {"twr": 0.032},
                },
                "source": "core-only-fallback",
            },
            "date_range",
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
