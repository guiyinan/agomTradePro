"""Catalog projection for the governed provider connection workflow."""

from types import SimpleNamespace
from unittest.mock import patch

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


def test_sync_mcp_tools_projects_provider_connection_test_replacement() -> None:
    manifest = SimpleNamespace(
        capability_key="data_center.run.provider_connection_test",
        summary="Preview and run a provider connection probe.",
        description="Governed staff-only provider probe workflow.",
        owner_app="data_center",
        tags=("data_center", "provider", "connection_test", "write"),
        audit_tags=("data_center:provider_connection_test", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"provider_id": {"type": "integer"}},
            "required": ["provider_id"],
        },
        risk_level="medium",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("test_data_center_provider_connection",),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(
                    name="agom_capability_call",
                    description="core",
                    inputSchema={},
                ),
                SimpleNamespace(
                    name="test_data_center_provider_connection",
                    description="legacy provider connection test",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.data_center.run.provider_connection_test"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["replacement_for"] == ["test_data_center_provider_connection"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:provider_connection_test",
        "mcp:write",
    ]

    legacy = by_key["mcp_tool.test_data_center_provider_connection"]
    assert legacy.execution_target["replacement_capability_key"] == (
        "data_center.run.provider_connection_test"
    )
    assert legacy.enabled_for_terminal is False
