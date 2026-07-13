# ruff: noqa: F403, F405
"""Core-only read matrix for hedge."""

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
            "hedge.compute.correlation_matrix",
            "hedge_compute_correlation_matrix",
            (
                "get_hedge_correlation_matrix",
                "get_correlation_matrix",
            ),
            {
                "asset_codes": ["510300", "511260"],
                "window_days": 30,
            },
            {
                "asset_codes": ["510300", "511260"],
                "window_days": 30,
                "matrix": {
                    "510300": {"510300": 1.0, "511260": -0.42},
                    "511260": {"510300": -0.42, "511260": 1.0},
                },
                "source": "core-only-fallback",
            },
            "-0.42",
        ),
        (
            "hedge.read.pair_catalog",
            "hedge_read_pair_catalog",
            ("list_hedge_pairs",),
            {},
            {
                "pairs": [
                    {
                        "id": 2,
                        "name": "股债对冲",
                        "hedge_method": "beta",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "股债对冲",
        ),
        (
            "hedge.read.pair_detail",
            "hedge_read_pair_detail",
            ("get_hedge_pair_info",),
            {"pair_name": "股债对冲"},
            {
                "pair_name": "股债对冲",
                "pair": {
                    "id": 2,
                    "name": "股债对冲",
                    "long_asset": "510300",
                    "hedge_asset": "511260",
                },
                "source": "core-only-fallback",
            },
            "511260",
        ),
        (
            "hedge.read.alert_list",
            "hedge_read_alert_list",
            ("get_hedge_alerts",),
            {},
            {
                "alerts": [
                    {
                        "id": 9,
                        "pair_name": "股债对冲",
                        "severity": "warning",
                    }
                ],
                "total_count": 1,
                "query": {
                    "days": 7,
                    "is_resolved": False,
                },
                "source": "core-only-fallback",
            },
            "warning",
        ),
        (
            "hedge.read.portfolio_state",
            "hedge_read_portfolio_state",
            ("get_hedge_portfolio_state",),
            {"pair_name": "股债对冲"},
            {
                "pair_name": "股债对冲",
                "state": {
                    "pair_name": "股债对冲",
                    "trade_date": "2026-07-10",
                    "hedge_effectiveness": 0.72,
                },
                "source": "core-only-fallback",
            },
            "0.72",
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
