# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_audit."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_audit_validation_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="audit.start.threshold_validation",
        summary="Preview first, then run threshold validation.",
        description="Governed staff-only audit validation workflow.",
        owner_app="audit",
        tags=("audit", "threshold", "validation", "workflow", "write"),
        audit_tags=("audit:threshold_validation", "mcp:write"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("run_audit_validation",),
    )
    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name="run_audit_validation",
                    description="run audit validation",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.audit.start.threshold_validation"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["replacement_for"] == ["run_audit_validation"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "audit:threshold_validation",
        "mcp:write",
    ]
    assert governed.semantic_key == "audit.start.threshold_validation"

    legacy = by_key["mcp_tool.run_audit_validation"]
    assert legacy.execution_target["replacement_capability_key"] == (
        "audit.start.threshold_validation"
    )
    assert legacy.semantic_key == "audit.start.threshold_validation"
    assert legacy.enabled_for_terminal is False
