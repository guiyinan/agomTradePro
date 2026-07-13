# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_dashboard."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_dashboard_weekly_report_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="dashboard.create.auto_advisor_weekly_report",
        summary="Preview and persist an Auto Advisor weekly report.",
        description="Governed owner-scoped weekly report persistence.",
        owner_app="dashboard",
        tags=("dashboard", "auto_advisor", "weekly_report", "create", "write"),
        audit_tags=("dashboard:create_auto_advisor_weekly_report", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["integer", "string"]},
                "as_of": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id", "as_of"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_auto_advisor_weekly_report",),
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
                    name="create_auto_advisor_weekly_report",
                    description="create Auto Advisor weekly report",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.dashboard.create.auto_advisor_weekly_report"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_auto_advisor_weekly_report"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "dashboard:create_auto_advisor_weekly_report",
        "mcp:write",
    ]
    assert governed.semantic_key == "dashboard.create.auto_advisor_weekly_report"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.create_auto_advisor_weekly_report"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == (
        "dashboard.create.auto_advisor_weekly_report"
    )
    assert legacy.semantic_key == "dashboard.create.auto_advisor_weekly_report"
    assert legacy.enabled_for_terminal is False
