# ruff: noqa: F403, F405
"""Core-only read matrix for simulated_trading."""

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
            "simulated_trading.read.daily_inspection_list",
            "simulated_trading_read_daily_inspection_list",
            ("list_simulated_daily_inspections",),
            {
                "account_id": 7,
                "limit": 10,
                "inspection_date": "2026-07-10",
            },
            {
                "account_id": 7,
                "reports": [
                    {
                        "report_id": 3,
                        "inspection_date": "2026-07-10",
                    }
                ],
                "total_count": 1,
                "query": {
                    "limit": 10,
                    "inspection_date": "2026-07-10",
                },
                "source": "core-only-fallback",
            },
            "report_id",
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
