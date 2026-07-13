# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_events."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_events_publish_event_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="events.publish.event",
        summary="Preview first, then publish one canonical domain event.",
        description="Governed staff-only domain event publication capability.",
        owner_app="events",
        tags=("events", "domain-event", "publish", "workflow", "write"),
        audit_tags=("events:publish", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_type": {"type": "string"},
                "payload": {"type": "object"},
                "occurred_at": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": [
                "event_type",
                "payload",
                "occurred_at",
                "idempotency_key",
            ],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("publish_event",),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name="publish_event",
                    description="publish domain event",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.events.publish.event"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["publish_event"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "events:publish",
        "mcp:write",
    ]
    assert governed.semantic_key == "events.publish.event"

    legacy = by_key["mcp_tool.publish_event"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "events.publish.event"
    assert legacy.semantic_key == "events.publish.event"
    assert legacy.enabled_for_terminal is False
