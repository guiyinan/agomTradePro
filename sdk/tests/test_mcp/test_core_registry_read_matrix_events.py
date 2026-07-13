# ruff: noqa: F403, F405
"""Core-only read matrix for events."""

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
            "events.read.query",
            "query_events",
            ("query_events",),
            {"event_type": "regime_changed", "limit": 10},
            {
                "success": True,
                "events": [
                    {
                        "event_id": "evt-1",
                        "event_type": "regime_changed",
                    }
                ],
                "total_count": 1,
                "queried_at": "2026-07-10T11:00:00+00:00",
                "has_more": False,
                "source": "core-only-fallback",
            },
            "evt-1",
        ),
        (
            "events.read.metrics",
            "get_event_metrics",
            ("get_event_metrics",),
            {},
            {
                "success": True,
                "metrics": {
                    "total_published": 14,
                    "total_processed": 13,
                    "total_failed": 1,
                },
                "events_by_type": {"regime_changed": 4},
                "active_subscriptions": 3,
                "queue_size": 0,
                "source": "core-only-fallback",
            },
            "total_processed",
        ),
        (
            "events.read.status",
            "get_event_bus_status",
            ("get_event_bus_status",),
            {},
            {
                "success": True,
                "is_running": True,
                "total_subscribers": 3,
                "queue_size": 0,
                "last_event_at": "2026-07-10T11:00:00+00:00",
                "uptime_seconds": 0,
                "source": "core-only-fallback",
            },
            "is_running",
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
