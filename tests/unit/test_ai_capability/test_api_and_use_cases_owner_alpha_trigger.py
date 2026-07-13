# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_alpha_trigger."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_alpha_trigger_update_candidate_status_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="alpha_trigger.update.candidate_status",
        summary="Preview first, then update the alpha candidate status.",
        description="Governed write capability for alpha trigger candidate status updates.",
        owner_app="alpha_trigger",
        tags=("alpha_trigger", "candidate", "status", "update", "write"),
        audit_tags=("alpha_trigger:update_candidate_status", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"candidate_id": {"type": "string"}, "status": {"type": "string"}},
            "required": ["candidate_id", "status"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_alpha_candidate_status",),
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
                    name="update_alpha_candidate_status",
                    description="alpha candidate status update",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.alpha_trigger.update.candidate_status"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_alpha_candidate_status"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "alpha_trigger:update_candidate_status",
        "mcp:write",
    ]
    assert governed.semantic_key == "alpha_trigger.update.candidate_status"

    legacy = by_key["mcp_tool.update_alpha_candidate_status"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "alpha_trigger.update.candidate_status"
    )
    assert legacy.semantic_key == "alpha_trigger.update.candidate_status"
    assert legacy.enabled_for_terminal is False
