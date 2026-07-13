# ruff: noqa: F403, F405
"""Core-only read matrix for backtest."""

from .core_registry_support import *


def test_backtest_equity_curve_uses_canonical_sdk_through_core_registry(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls = []
    backtest = SimpleNamespace(
        get_equity_curve_payload=lambda backtest_id: calls.append(backtest_id)
        or {
            "backtest_id": backtest_id,
            "status": "completed",
            "curve": [{"date": "2026-01-31", "value": 105000.0}],
            "point_count": 1,
        }
    )
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(backtest=backtest),
    )

    manifest = CapabilityRegistryLoader().build_registry()[
        "backtest.read.equity_curve"
    ]
    assert manifest.executor_ref in server_module.INTERNAL_LEGACY_TOOL_FALLBACKS
    assert manifest.legacy_tool_names == ("get_backtest_equity_curve",)
    assert manifest.required_roles == ("staff",)

    response = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "backtest.read.equity_curve",
                "arguments": {"backtest_id": 17},
            },
        )
    )

    assert "completed" in str(response)
    assert "105000.0" in str(response)
    assert calls == [17]


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
            "backtest.read.detail",
            "get_backtest_result",
            ("get_backtest_result",),
            {"backtest_id": 17},
            {
                "id": 17,
                "status": "completed",
                "total_return": 0.12,
                "annual_return": 0.08,
                "max_drawdown": -0.05,
                "sharpe_ratio": 1.4,
                "source": "core-only-fallback",
            },
            "1.4",
        ),
        (
            "backtest.read.list",
            "list_backtests",
            ("list_backtests",),
            {"status": "completed", "limit": 10},
            {
                "backtests": [
                    {
                        "id": 17,
                        "status": "completed",
                        "total_return": 0.12,
                        "annual_return": 0.08,
                        "max_drawdown": -0.05,
                        "sharpe_ratio": 1.4,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "total_count",
        ),
        (
            "backtest.read.equity_curve",
            "backtest_read_equity_curve",
            ("get_backtest_equity_curve",),
            {"backtest_id": 17},
            {
                "backtest_id": 17,
                "status": "completed",
                "curve": [{"date": "2026-01-31", "value": 105000.0}],
                "point_count": 1,
                "source": "core-only-fallback",
            },
            "105000.0",
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
