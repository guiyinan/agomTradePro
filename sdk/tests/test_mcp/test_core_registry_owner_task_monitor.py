# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_task_monitor."""

from .core_registry_support import *


@pytest.mark.parametrize(
    ("capability_key", "legacy_tool_name", "arguments", "payload", "expected"),
    [
        (
            "system.read.task_monitor.statistics",
            "get_task_monitor_statistics",
            {"task_name": "sync.macro", "days": 7},
            {
                "task_name": "sync.macro",
                "total_executions": 8,
                "successful_executions": 7,
                "failed_executions": 1,
                "success_rate": 0.875,
                "source": "core-only-fallback",
            },
            "sync.macro",
        ),
        (
            "task_monitor.read.task_status",
            "get_task_monitor_status",
            {"task_id": "task-123"},
            {
                "task_id": "task-123",
                "task_name": "sync.macro",
                "status": "success",
                "is_success": True,
                "is_failure": False,
                "source": "core-only-fallback",
            },
            "task-123",
        ),
        (
            "task_monitor.read.task_list",
            "list_task_monitor_tasks",
            {},
            {
                "total": 1,
                "items": [{"task_id": "task-123", "status": "success"}],
                "source": "core-only-fallback",
            },
            "task-123",
        ),
        (
            "task_monitor.read.dashboard",
            "get_task_monitor_dashboard",
            {},
            {
                "recent_failures": {"count": 1, "items": [{"task_id": "failed-1"}]},
                "celery_health": {"is_healthy": True, "active_workers_count": 2},
                "source": "core-only-fallback",
            },
            "failed-1",
        ),
        (
            "task_monitor.read.celery_health",
            "get_task_monitor_celery_health",
            {},
            {
                "is_healthy": True,
                "broker_reachable": True,
                "backend_reachable": True,
                "active_workers": ["worker@node"],
                "active_tasks_count": 2,
                "pending_tasks_count": 0,
                "scheduled_tasks_count": 1,
                "last_check": "2026-07-10T15:00:00+08:00",
                "source": "core-only-fallback",
            },
            "worker@node",
        ),
    ],
)
def test_agom_capability_call_reads_task_monitor_family_in_core_only_mode(
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


def test_task_monitor_snapshot_workflow_uses_zero_argument_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_task_monitor_dashboard",
        lambda **kwargs: {
            "recent_failures": {"count": 0, "items": []},
            "celery_health": {"is_healthy": True},
            "source": "dashboard-fallback",
        },
    )
    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_task_monitor_celery_health",
        lambda **kwargs: {
            "is_healthy": True,
            "active_workers": ["worker@node"],
            "source": "health-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_workflow_start",
            {
                "workflow_key": "ops.task_monitor_snapshot",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "task_monitor.read.dashboard" in rendered
    assert "task_monitor.read.celery_health" in rendered
    assert "dashboard-fallback" in rendered
    assert "health-fallback" in rendered
