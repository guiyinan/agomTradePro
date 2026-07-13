# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_task_monitor."""

from .api_and_use_cases_support import *


@pytest.mark.parametrize(
    ("capability_key", "legacy_tool_name", "input_schema"),
    [
        (
            "system.read.task_monitor.statistics",
            "get_task_monitor_statistics",
            {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string"},
                    "days": {"type": "integer"},
                },
                "required": ["task_name"],
            },
        ),
        (
            "task_monitor.read.task_status",
            "get_task_monitor_status",
            {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        (
            "task_monitor.read.task_list",
            "list_task_monitor_tasks",
            {"type": "object", "properties": {}, "required": []},
        ),
        (
            "task_monitor.read.dashboard",
            "get_task_monitor_dashboard",
            {"type": "object", "properties": {}, "required": []},
        ),
        (
            "task_monitor.read.celery_health",
            "get_task_monitor_celery_health",
            {"type": "object", "properties": {}, "required": []},
        ),
    ],
)
def test_sync_mcp_tools_preserves_task_monitor_read_family_metadata(
    capability_key,
    legacy_tool_name,
    input_schema,
):
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key=capability_key,
        summary=f"Read governed task monitor capability {capability_key}.",
        description=f"Return the canonical task monitor payload for {capability_key}.",
        owner_app="task_monitor",
        tags=("task_monitor", "operations", "read"),
        input_schema=input_schema,
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=(legacy_tool_name,),
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
                    name=legacy_tool_name,
                    description=f"legacy task monitor tool {legacy_tool_name}",
                    inputSchema=input_schema,
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key[f"mcp_tool.{capability_key}"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == capability_key
    assert governed.execution_target["replacement_for"] == [legacy_tool_name]
    assert governed.semantic_key == capability_key
    assert governed.input_schema == input_schema
    assert governed.enabled_for_terminal is True

    legacy = by_key[f"mcp_tool.{legacy_tool_name}"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == capability_key
    assert legacy.semantic_key == capability_key
    assert legacy.enabled_for_terminal is False
