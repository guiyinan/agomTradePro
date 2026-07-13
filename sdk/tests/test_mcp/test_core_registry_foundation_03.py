# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: foundation."""

from .core_registry_support import *


def test_alpha_trigger_core_only_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _AlphaTrigger:
        def list_triggers(self):
            calls.append(("list_triggers", None))
            return [{"trigger_id": "trigger-001"}]

        def list_candidates(self):
            calls.append(("list_candidates", None))
            return [{"candidate_id": "candidate-001"}]

        def get_candidate(self, candidate_id):
            calls.append(("get_candidate", candidate_id))
            return {
                "success": True,
                "result": {
                    "candidate_id": candidate_id,
                    "asset_code": "600519.SH",
                },
            }

        def performance(self, *, days=None, trigger_id=None):
            calls.append(("performance", (days, trigger_id)))
            return {
                "success": True,
                "data": [{"trigger_id": trigger_id}],
                "summary": {
                    "days": days,
                    "trigger_id": trigger_id,
                    "total_triggers": 1,
                },
            }

    class _Client:
        alpha_trigger = _AlphaTrigger()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["list_alpha_triggers"]() == {
        "triggers": [{"trigger_id": "trigger-001"}],
        "total_count": 1,
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["list_alpha_candidates"]() == {
        "candidates": [{"candidate_id": "candidate-001"}],
        "total_count": 1,
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_alpha_candidate"]("candidate-001") == {
        "candidate_id": "candidate-001",
        "asset_code": "600519.SH",
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["alpha_trigger_read_performance"](
        days=30,
        trigger_id="trigger-001",
    ) == {
        "success": True,
        "data": [{"trigger_id": "trigger-001"}],
        "summary": {
            "days": 30,
            "trigger_id": "trigger-001",
            "total_triggers": 1,
        },
    }
    assert calls == [
        ("list_triggers", None),
        ("list_candidates", None),
        ("get_candidate", "candidate-001"),
        ("performance", (30, "trigger-001")),
    ]


@pytest.mark.parametrize(
    ("capability_key", "legacy_tool_name", "arguments", "payload", "expected"),
    [
        (
            "system.read.policy.status",
            "get_policy_status",
            {},
            {
                "current_gear": "stimulus",
                "observed_at": "2026-07-10",
                "recent_events_count": 1,
                "source": "core-only-fallback",
            },
            "stimulus",
        ),
        (
            "regime.read.history",
            "get_regime_history",
            {"start_date": "2026-07-01", "end_date": "2026-07-10", "limit": 1},
            {
                "history": [
                    {
                        "dominant_regime": "Recovery",
                        "observed_at": "2026-07-09",
                        "confidence": 0.82,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "Recovery",
        ),
        (
            "policy.read.events",
            "get_policy_events",
            {"start_date": "2026-07-01", "end_date": "2026-07-10"},
            {
                "events": [
                    {
                        "event_date": "2026-07-09",
                        "event_type": "policy",
                        "description": "Targeted liquidity support.",
                        "gear": "stimulus",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "Targeted liquidity support",
        ),
    ],
)
def test_agom_capability_call_reads_regime_policy_family_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    capability_key,
    legacy_tool_name,
    arguments,
    payload,
    expected,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        legacy_tool_name,
        lambda **kwargs: payload,
    )

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


def test_server_can_enable_legacy_surface_when_requested(legacy_enabled_mcp_server):
    tools = asyncio.run(legacy_enabled_mcp_server.list_tools())
    names = {tool.name for tool in tools}

    for tool_name in CORE_TOOL_NAMES:
        assert tool_name in names
    assert "get_current_regime" in names
