# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_task_monitor."""

from .core_registry_support import *


@pytest.mark.parametrize("mode", ["core_only_mcp_server", "legacy_enabled_mcp_server"])
@pytest.mark.parametrize(
    ("capability", "arguments", "path", "params", "http_status", "wire_code"),
    [
        (
            "task_monitor.read.task_status",
            {"task_id": "missing"},
            "/api/system/status/missing/",
            None,
            404,
            "TASK_NOT_FOUND",
        ),
        (
            "system.read.task_monitor.statistics",
            {"task_name": "demo.task"},
            "/api/system/statistics/",
            {"task_name": "demo.task", "days": 7},
            503,
            "TASK_MONITOR_UNAVAILABLE",
        ),
        (
            "system.read.task_monitor.statistics",
            {"task_name": ""},
            "/api/system/statistics/",
            {"days": 7},
            400,
            "MISSING_PARAMETER",
        ),
    ],
)
def test_task_read_preserves_upstream_error(
    request,
    monkeypatch,
    mock_config,
    mode,
    capability,
    arguments,
    path,
    params,
    http_status,
    wire_code,
) -> None:
    """The registered MCP tool preserves the error returned to its SDK transport."""
    mcp = request.getfixturevalue(mode)
    import agomtradepro_mcp.audit as audit
    from agomtradepro.transport import use_request_transport

    monkeypatch.setattr(audit, "_audit_logger", SimpleNamespace(log_mcp_call=lambda **kwargs: None))
    requests = []

    def upstream(**kwargs):
        requests.append((kwargs["method"], kwargs["url"], kwargs["params"]))
        return SimpleNamespace(
            status_code=http_status,
            json=lambda: {"code": wire_code, "internal": "private-marker"},
        )

    with use_request_transport(SimpleNamespace(request=upstream)):
        response = asyncio.run(
            mcp.call_tool(
                "agom_capability_call", {"capability_key": capability, "arguments": arguments}
            )
        )[1]

    assert requests == [("GET", mock_config["base_url"] + path, params)]
    assert response["ok"] is False
    assert response["error"]["code"] == wire_code.lower()
    assert response["error"]["upstream_status_code"] == http_status
    assert "private-marker" not in str(response)


def test_task_monitor_phase_schema_declares_count_units() -> None:
    """Task Monitor MCP output documents the phase count units exposed by the API."""

    from agomtradepro_mcp.registry.modules.owners.task_monitor_read_capabilities import (
        _TASK_ATTEMPT_OUTPUT_SCHEMA,
        _TASK_STATUS_OUTPUT_PROPERTIES,
    )

    expected_unit_schema = {"type": ["string", "null"]}
    status_phase_properties = _TASK_STATUS_OUTPUT_PROPERTIES["phase_results"]["items"]["properties"]
    attempt_phase_properties = _TASK_ATTEMPT_OUTPUT_SCHEMA["properties"]["phase_results"]["items"][
        "properties"
    ]

    assert status_phase_properties["count_unit"] == expected_unit_schema
    assert status_phase_properties["stored_count_unit"] == expected_unit_schema
    assert attempt_phase_properties["count_unit"] == expected_unit_schema
    assert attempt_phase_properties["stored_count_unit"] == expected_unit_schema


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
