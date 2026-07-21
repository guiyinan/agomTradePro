# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_pulse."""

from .core_registry_support import *


def test_agom_capability_call_reads_pulse_current_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_pulse_current",
        lambda **kwargs: {
            "composite_score": 0.73,
            "observed_at": "2026-07-10",
            "indicators": [
                {
                    "code": "000300.SH",
                    "value": 4739.23,
                    "observed_at": "2026-07-10",
                    "source_kind": "quote_current_price",
                }
            ],
            "contract": {
                "market_data_as_of": "2026-07-10",
                "indicator_observed_at": {"000300.SH": "2026-07-10"},
                "must_not_use_for_decision": False,
            },
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "pulse.read.current",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "pulse.read.current" in rendered
    assert "0.73" in rendered
    assert "quote_current_price" in rendered
    assert "market_data_as_of" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_pulse_history_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_pulse_history",
        lambda **kwargs: [
            {
                "observed_at": "2026-07-10",
                "composite_score": 0.73,
                "regime_strength": "strong",
                "source": "core-only-fallback",
            },
            {
                "observed_at": "2026-07-09",
                "composite_score": 0.41,
                "regime_strength": "moderate",
                "source": "core-only-fallback",
            },
        ],
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "pulse.read.history",
                "arguments": {"limit": 2},
            },
        )
    )

    rendered = str(result)
    assert "pulse.read.history" in rendered
    assert "2026-07-10" in rendered
    assert "core-only-fallback" in rendered
