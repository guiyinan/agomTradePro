from types import SimpleNamespace
from unittest.mock import patch

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


def test_sync_mcp_tools_maps_validate_all_to_explicit_threshold_validation():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="audit.start.threshold_validation",
        summary="Preview first, then validate explicit dates.",
        description="Governed staff-only Audit validation workflow.",
        owner_app="audit",
        tags=("audit", "threshold", "validation", "workflow", "write"),
        audit_tags=("audit:threshold_validation", "mcp:write"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("run_audit_validation", "validate_all_indicators"),
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
                    name="run_audit_validation", description="run validation", inputSchema={}
                ),
                SimpleNamespace(
                    name="validate_all_indicators",
                    description="validate default range",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.audit.start.threshold_validation"]
    assert governed.execution_target["replacement_for"] == [
        "run_audit_validation",
        "validate_all_indicators",
    ]
    legacy = by_key["mcp_tool.validate_all_indicators"]
    assert legacy.execution_target["replacement_capability_key"] == (
        "audit.start.threshold_validation"
    )
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_audit_attribution_report_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="audit.create.attribution_report",
        summary="Preview first, then generate an attribution report.",
        description="Governed staff-only Audit report workflow.",
        owner_app="audit",
        tags=("audit", "attribution", "report", "create", "workflow"),
        audit_tags=("audit:attribution_report", "mcp:write"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("generate_audit_report",),
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
                    name="generate_audit_report",
                    description="generate audit report",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.audit.create.attribution_report"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["replacement_for"] == ["generate_audit_report"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "audit:attribution_report",
        "mcp:write",
    ]
    assert governed.semantic_key == "audit.create.attribution_report"

    legacy = by_key["mcp_tool.generate_audit_report"]
    assert legacy.execution_target["replacement_capability_key"] == (
        "audit.create.attribution_report"
    )
    assert legacy.semantic_key == "audit.create.attribution_report"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_audit_threshold_update_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="audit.update.threshold_levels",
        summary="Preview first, then update threshold levels.",
        description="Governed staff-only Audit threshold update.",
        owner_app="audit",
        tags=("audit", "threshold", "configuration", "update", "write"),
        audit_tags=("audit:threshold_levels", "mcp:write"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_audit_threshold",),
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
                    name="update_audit_threshold",
                    description="update audit threshold",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.audit.update.threshold_levels"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["replacement_for"] == ["update_audit_threshold"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "audit:threshold_levels",
        "mcp:write",
    ]
    assert governed.semantic_key == "audit.update.threshold_levels"

    legacy = by_key["mcp_tool.update_audit_threshold"]
    assert legacy.execution_target["replacement_capability_key"] == (
        "audit.update.threshold_levels"
    )
    assert legacy.semantic_key == "audit.update.threshold_levels"
    assert legacy.enabled_for_terminal is False
