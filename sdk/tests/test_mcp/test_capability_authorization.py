"""Authorization tests for governed MCP capability execution."""

from __future__ import annotations

from unittest.mock import Mock

from agomtradepro_mcp.registry.dispatcher import CapabilityDispatcher
from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _staff_manifest() -> CapabilityManifest:
    """Return one staff-only capability contract."""

    return CapabilityManifest(
        capability_key="system.update.setting",
        title="Update Setting",
        summary="Update one protected setting.",
        description="Update one protected setting for authorization tests.",
        owner_app="config_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="update_setting",
        input_schema={"type": "object", "properties": {}, "required": []},
        required_roles=("staff",),
    )


def test_staff_capability_is_hidden_from_non_staff_discovery() -> None:
    manifest = _staff_manifest()
    dispatcher = CapabilityDispatcher(
        registry={manifest.capability_key: manifest},
        legacy_tool_caller=Mock(),
        internal_handler_caller=Mock(),
        role_provider=lambda: "read_only",
    )

    assert dispatcher.list_capabilities() == []
    assert dispatcher.search(query="setting") == []


def test_staff_capability_rejects_non_staff_before_handler_execution() -> None:
    manifest = _staff_manifest()
    handler = Mock()
    dispatcher = CapabilityDispatcher(
        registry={manifest.capability_key: manifest},
        legacy_tool_caller=Mock(),
        internal_handler_caller=handler,
        role_provider=lambda: "read_only",
    )

    result = dispatcher.call(
        capability_key=manifest.capability_key,
        arguments={},
        context={"mcp_role": "admin"},
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "capability_forbidden"
    assert result["required_roles"] == ["staff"]
    handler.assert_not_called()


def test_staff_capability_allows_trusted_admin_role() -> None:
    manifest = _staff_manifest()
    handler = Mock(return_value={"updated": True})
    dispatcher = CapabilityDispatcher(
        registry={manifest.capability_key: manifest},
        legacy_tool_caller=Mock(),
        internal_handler_caller=handler,
        role_provider=lambda: "admin",
    )

    result = dispatcher.call(capability_key=manifest.capability_key, arguments={})

    assert result["ok"] is True
    assert result["result"] == {"updated": True}
    handler.assert_called_once_with("update_setting", {})
