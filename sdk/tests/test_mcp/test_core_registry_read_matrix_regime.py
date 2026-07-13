# ruff: noqa: F403, F405
"""Core-only read matrix for regime."""

from .core_registry_support import *


def test_regime_action_recommendation_uses_canonical_sdk_through_core_registry(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls = []
    pulse = SimpleNamespace(
        get_action_recommendation=lambda: calls.append("action")
        or {
            "success": True,
            "data": {
                "asset_weights": {"equity": 0.55, "bond": 0.25, "cash": 0.20},
                "risk_budget_pct": 0.75,
                "position_limit_pct": 0.10,
                "recommended_sectors": ["科技"],
                "benefiting_styles": ["成长"],
                "hedge_recommendation": None,
                "reasoning": "Recovery with reliable Pulse",
                "confidence": 0.72,
                "must_not_use_for_decision": False,
                "blocked_reason": "",
                "blocked_code": "",
                "pulse_is_reliable": True,
                "stale_indicator_codes": [],
                "contract": {
                    "must_not_use_for_decision": False,
                    "pulse_is_reliable": True,
                },
            },
        }
    )
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(pulse=pulse),
    )

    manifest = CapabilityRegistryLoader().build_registry()[
        "regime.read.action_recommendation"
    ]
    assert manifest.executor_ref in server_module.INTERNAL_LEGACY_TOOL_FALLBACKS
    assert manifest.legacy_tool_names == ("get_action_recommendation",)

    response = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "regime.read.action_recommendation",
                "arguments": {},
            },
        )
    )

    assert "completed" in str(response)
    assert "Recovery with reliable Pulse" in str(response)
    assert calls == ["action"]


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
            "regime.read.navigator",
            "get_regime_navigator",
            ("get_regime_navigator",),
            {},
            {
                "regime_name": "Recovery",
                "confidence": 0.61,
                "movement": {
                    "direction": "transitioning",
                    "transition_target": "Overheat",
                },
                "asset_guidance": {
                    "risk_budget_pct": 0.85,
                    "recommended_sectors": ["消费", "科技"],
                },
                "watch_indicators": [{"code": "PMI", "significance": "high"}],
                "source": "core-only-fallback",
            },
            "Overheat",
        ),
        (
            "regime.read.distribution",
            "get_regime_distribution",
            ("get_regime_distribution",),
            {
                "start_date": "2026-07-01",
                "end_date": "2026-07-10",
            },
            {
                "distribution": {
                    "Recovery": 3,
                    "Overheat": 1,
                    "Stagflation": 0,
                    "Deflation": 1,
                },
                "total_count": 5,
                "source": "core-only-fallback",
            },
            "Deflation",
        ),
        (
            "regime.compute.calculate",
            "calculate_regime",
            ("calculate_regime",),
            {
                "as_of_date": "2026-07-10",
                "use_pit": True,
                "growth_indicator": "PMI",
                "inflation_indicator": "CPI",
                "data_source": "akshare",
            },
            {
                "success": True,
                "snapshot": {
                    "observed_at": "2026-07-10",
                    "dominant_regime": "Recovery",
                    "confidence": 0.72,
                },
                "warnings": [],
                "error": None,
                "raw_data": {
                    "growth": [{"date": "2026-07-10", "value": 50.8}],
                    "inflation": [{"date": "2026-07-10", "value": 1.8}],
                },
                "source": "core-only-fallback",
            },
            "Recovery",
        ),
        (
            "regime.read.action_recommendation",
            "regime_read_action_recommendation",
            ("get_action_recommendation",),
            {},
            {
                "asset_weights": {"equity": 0.55, "bond": 0.25, "cash": 0.20},
                "risk_budget_pct": 0.75,
                "position_limit_pct": 0.10,
                "recommended_sectors": ["科技"],
                "benefiting_styles": ["成长"],
                "must_not_use_for_decision": False,
                "blocked_reason": "",
                "blocked_code": "",
                "pulse_is_reliable": True,
                "stale_indicator_codes": [],
                "contract": {"must_not_use_for_decision": False},
                "source": "core-only-fallback",
            },
            "risk_budget_pct",
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
