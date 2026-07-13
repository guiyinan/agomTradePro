# ruff: noqa: F403, F405
"""Core-only read matrix for asset_analysis."""

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
            "asset_analysis.read.weight_config_catalog",
            "asset_analysis_read_weight_config_catalog",
            ("get_asset_weight_configs",),
            {},
            {
                "configs": {
                    "default": {
                        "name": "default",
                        "weights": {
                            "regime": 0.4,
                            "policy": 0.25,
                            "sentiment": 0.2,
                            "signal": 0.15,
                        },
                    }
                },
                "active": "default",
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "default",
        ),
        (
            "asset_analysis.read.current_weight",
            "asset_analysis_read_current_weight",
            ("get_asset_current_weight",),
            {},
            {
                "success": True,
                "weights": {
                    "regime": 0.4,
                    "policy": 0.25,
                    "sentiment": 0.2,
                    "signal": 0.15,
                },
                "asset_type": None,
                "market_condition": None,
                "source": "core-only-fallback",
            },
            "regime",
        ),
        (
            "asset_analysis.read.pool_summary",
            "asset_analysis_read_pool_summary",
            ("asset_pool_summary",),
            {"asset_type": "equity"},
            {
                "success": True,
                "asset_type": "equity",
                "summary": {
                    "investable": 2,
                    "watch": 1,
                    "candidate": 0,
                    "prohibited": 0,
                    "total": 3,
                },
                "source": "core-only-fallback",
            },
            "investable",
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
