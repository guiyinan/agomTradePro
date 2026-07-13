# ruff: noqa: F403, F405
"""Core-only read matrix for realtime."""

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
            "realtime.read.price",
            "get_realtime_price",
            ("get_realtime_price",),
            {"asset_code": "510300.SH"},
            {
                "asset_code": "510300.SH",
                "current_price": 4.25,
                "price_change_percent": 0.83,
                "updated_at": "2026-07-10T14:30:00+08:00",
                "source": "core-only-fallback",
            },
            "4.25",
        ),
        (
            "realtime.read.price_batch",
            "get_multiple_realtime_prices",
            ("get_multiple_realtime_prices",),
            {"asset_codes": ["510300.SH", "159915.SZ"]},
            {
                "prices": {
                    "510300.SH": {"current_price": 4.25},
                    "159915.SZ": {"current_price": 2.18},
                },
                "total_count": 2,
                "source": "core-only-fallback",
            },
            "159915.SZ",
        ),
        (
            "realtime.read.market_summary",
            "get_market_summary",
            ("get_market_summary",),
            {},
            {
                "success": True,
                "stats_available": False,
                "sh_index": 3200.5,
                "cyb_index": 2100.1,
                "source": "core-only-fallback",
            },
            "3200.5",
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
