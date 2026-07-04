from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.task_monitor.domain.entities import (
    CeleryHealthStatus,
    TaskExecutionRecord,
    TaskPriority,
    TaskStatus,
)
from apps.task_monitor.infrastructure.models import TaskExecutionModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="task_monitor_user",
        password="testpass123",
        email="task-monitor@example.com",
    )


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="task_monitor_staff",
        password="testpass123",
        email="task-monitor-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


def _readiness_monitor_payload():
    return {
        "status": "in_progress",
        "daily_state": {
            "code": "latest_closed_day_accepted",
            "severity": "ok",
            "title": "最新收盘日已验收",
            "message": "当前最新已收盘交易日已有有效证据，等待下一交易日收盘。",
        },
        "monitor_gate": {
            "ok": True,
            "state": "wait_for_post_close",
            "reason": "target_date_not_closed",
            "next_action": "wait_for_post_close",
            "next_check_after": "2026-07-06T16:10:00+08:00",
            "command": None,
        },
        "window": {
            "accepted": False,
            "accepted_days": 4,
            "required_days": 20,
            "remaining_days": 16,
            "latest_target_date": "2026-07-03",
            "next_required_date": "2026-07-06",
            "next_required_reason": "next_trading_day",
            "projected_completion_date": "2026-07-27",
            "projected_scheduler_completion_date": "2026-07-28",
        },
        "today": {
            "status_date": "2026-07-04",
            "latest_closed_date": "2026-07-03",
            "expected_latest_date": "2026-07-03",
            "latest_evidence_status": "ok",
            "latest_evidence_target_date": "2026-07-03",
            "latest_target_date": "2026-07-03",
        },
        "schedule": {
            "due_status": "pending",
            "scheduled_for": "2026-07-06T16:10:00+08:00",
            "grace_deadline": "2026-07-06T16:40:00+08:00",
            "next_check_after": "2026-07-06T16:10:00+08:00",
        },
        "next_action": {
            "action": "wait_for_post_close",
            "reason": "target_date_not_closed",
            "target_date": "2026-07-06",
            "command": None,
        },
        "scheduler_runtime": {
            "required": False,
            "status": "not_checked",
            "worker_process_count": None,
            "beat_process_count": None,
            "responsive_worker_count": None,
            "missing_queues": [],
            "missing_registered_tasks": [],
        },
        "decision_data": {
            "status": "blocked",
            "readiness_status": "blocked",
            "must_not_use_for_decision": True,
            "blocked_reasons": ["quote stale"],
        },
        "data_coverage": {
            "status": "ok",
            "universe": "active_stock",
            "asset_count": 304,
            "universe_quality": {
                "status": "ok",
                "minimum_active_a_share_count": 4000,
                "minimum_star_market_count": 200,
                "minimum_bse_count": 50,
                "exchange_counts": {"SSE": 2200, "SZSE": 3000, "BSE": 200},
                "board_counts": {
                    "star_market": 580,
                    "chinext": 1400,
                    "bse": 200,
                    "sh_main": 1600,
                    "sz_main": 1700,
                },
                "issues": [],
            },
            "domains": {
                "price": {
                    "covered_count": 304,
                    "missing_count": 0,
                    "latest_date": "2026-07-03",
                    "status": "ok",
                },
                "valuation": {
                    "covered_count": 304,
                    "missing_count": 0,
                    "latest_date": "2026-07-03",
                    "status": "ok",
                },
                "financial": {
                    "covered_count": 304,
                    "missing_count": 0,
                    "latest_date": "2026-03-31",
                    "status": "ok",
                },
            },
        },
        "operator_surfaces": {
            "status": "ok",
            "ai_capability": {
                "status": "ok",
                "catalog": {"total": 510, "enabled": 480, "disabled": 30},
                "mcp_tools": {
                    "total": 365,
                    "routing_enabled": 340,
                    "terminal_enabled": 330,
                    "chat_enabled": 320,
                    "agent_enabled": 340,
                    "requires_confirmation": 45,
                    "latest_sync_at": "2026-07-04T08:00:00+00:00",
                    "status": "ok",
                },
                "terminal_capabilities": {
                    "total": 18,
                    "routing_enabled": 17,
                    "terminal_enabled": 18,
                    "chat_enabled": 18,
                    "agent_enabled": 18,
                    "requires_confirmation": 2,
                    "latest_sync_at": "2026-07-04T08:00:00+00:00",
                    "status": "ok",
                },
            },
            "terminal": {
                "status": "ok",
                "terminal_commands": {
                    "active": 18,
                    "terminal_enabled": 18,
                    "requires_mcp": 6,
                    "api_type": 14,
                    "prompt_type": 4,
                    "status": "ok",
                },
                "tui_metadata": {
                    "status": "ok",
                    "version": "2026.07",
                    "schema_version": "tui-metadata.v3",
                    "modules": 12,
                    "screens": 37,
                    "actions": 180,
                    "default_screen": "command-center.overview",
                    "coverage_summary": {},
                },
            },
        },
        "blocking_issues": [],
        "accepted_dates": [
            "2026-06-30",
            "2026-07-01",
            "2026-07-02",
            "2026-07-03",
        ],
    }


@pytest.mark.django_db
def test_get_task_status_returns_serialized_task(authenticated_client):
    now = timezone.now()
    TaskExecutionModel.objects.create(
        task_id="task-123",
        task_name="demo.task",
        status="success",
        args=["a"],
        kwargs={"k": "v"},
        started_at=now - timedelta(seconds=5),
        finished_at=now,
        runtime_seconds=5.0,
        result="OK",
        retries=1,
        priority="high",
        queue="default",
        worker="worker@node",
    )

    response = authenticated_client.get("/api/system/status/task-123/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["task_id"] == "task-123"
    assert payload["task_name"] == "demo.task"
    assert payload["status"] == "success"
    assert payload["is_success"] is True
    assert payload["is_failure"] is False


@pytest.mark.django_db
def test_get_task_statistics_requires_task_name(authenticated_client):
    response = authenticated_client.get("/api/system/statistics/")

    assert response.status_code == 400
    assert response.json() == {
        "error": "task_name is required",
        "code": "MISSING_PARAMETER",
    }


@pytest.mark.django_db
def test_get_task_statistics_returns_summary(authenticated_client):
    now = timezone.now()
    TaskExecutionModel.objects.create(
        task_id="success-1",
        task_name="stats.task",
        status="success",
        args=[],
        kwargs={},
        started_at=now - timedelta(seconds=12),
        finished_at=now - timedelta(seconds=2),
        runtime_seconds=10.0,
        result="OK",
        retries=0,
        priority="normal",
    )
    TaskExecutionModel.objects.create(
        task_id="failure-1",
        task_name="stats.task",
        status="failure",
        args=[],
        kwargs={},
        started_at=now - timedelta(seconds=30),
        finished_at=now - timedelta(seconds=20),
        runtime_seconds=10.0,
        exception="boom",
        retries=1,
        priority="normal",
    )

    response = authenticated_client.get("/api/system/statistics/?task_name=stats.task&days=7")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_name"] == "stats.task"
    assert payload["total_executions"] == 2
    assert payload["successful_executions"] == 1
    assert payload["failed_executions"] == 1
    assert payload["average_runtime"] == 10.0
    assert payload["success_rate"] == 0.5
    assert payload["last_execution_status"] in {"success", "failure"}


@pytest.mark.django_db
def test_health_check_returns_service_unavailable_payload_on_exception(authenticated_client):
    with patch(
        "apps.task_monitor.interface.views.CheckCeleryHealthUseCase.execute",
        side_effect=RuntimeError("broker offline"),
    ):
        response = authenticated_client.get("/api/system/celery/health/")

    assert response.status_code == 503
    payload = response.json()
    assert payload["is_healthy"] is False
    assert payload["broker_reachable"] is False
    assert payload["backend_reachable"] is False
    assert payload["active_workers"] == []
    assert payload["error"] == "broker offline"


@pytest.mark.django_db
def test_dashboard_aggregates_recent_failures_and_health(authenticated_client):
    now = timezone.now()
    failures = SimpleNamespace(
        total=1,
        items=[
            TaskExecutionRecord(
                task_id="failed-1",
                task_name="demo.task",
                status=TaskStatus.FAILURE,
                args=(),
                kwargs={},
                started_at=now - timedelta(seconds=4),
                finished_at=now,
                result=None,
                exception="boom",
                traceback=None,
                runtime_seconds=4.0,
                retries=2,
                priority=TaskPriority.HIGH,
                queue="critical",
                worker="worker@node",
            )
        ],
    )
    health = CeleryHealthStatus(
        is_healthy=True,
        broker_reachable=True,
        backend_reachable=True,
        active_workers=["worker@node"],
        active_tasks_count=2,
        pending_tasks_count=1,
        scheduled_tasks_count=0,
        last_check=now,
    )

    with patch(
        "apps.task_monitor.interface.views.ListTasksUseCase.execute",
        return_value=failures,
    ) as mock_list, patch(
        "apps.task_monitor.interface.views.CheckCeleryHealthUseCase.execute",
        return_value=health,
    ) as mock_health:
        response = authenticated_client.get("/api/system/dashboard/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["recent_failures"]["count"] == 1
    assert payload["celery_health"]["is_healthy"] is True
    assert payload["celery_health"]["active_workers_count"] == 1
    assert payload["celery_health"]["active_tasks_count"] == 2
    mock_list.assert_called_once_with(failures_only=True, limit=10)
    mock_health.assert_called_once()


@pytest.mark.django_db
def test_scheduler_console_page_renders_periodic_tasks(client, staff_user):
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    client.force_login(staff_user)
    crontab = CrontabSchedule.objects.create(
        minute="45",
        hour="22",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Asia/Shanghai",
    )
    PeriodicTask.objects.create(
        name="decision-workspace-nightly-snapshot-refresh",
        task="apps.decision_rhythm.application.tasks.refresh_decision_workspace_snapshots",
        enabled=True,
        crontab=crontab,
        kwargs="{}",
        description="Nightly workspace refresh",
    )

    response = client.get("/ops/task-monitor/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "计划任务中心" in content
    assert "正在读取验收状态" in content
    assert "readiness-monitor.json" in content
    assert "decision-workspace-nightly-snapshot-refresh" in content
    assert "PeriodicTask 目录" in content
    assert "Celery 运行态" in content
    assert "收市后 Readiness 时间" in content
    assert 'name="quote_pre_refresh_time"' in content
    assert 'name="weekly_auto_advisor_time"' in content


@pytest.mark.django_db
def test_readiness_monitor_page_renders_lightweight_panel(client, staff_user):
    client.force_login(staff_user)

    response = client.get("/ops/task-monitor/readiness/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "验收监视器" in content
    assert "正在读取验收状态" in content
    assert "readiness-monitor.json" in content
    assert "20 个交易日验收窗口" in content
    assert "生产数据覆盖" in content
    assert "全市场口径" in content
    assert "操作入口覆盖" in content
    assert "MCP 工具" in content
    assert "TUI 元数据" in content
    assert "PeriodicTask 目录" not in content
    assert "Celery 运行态" not in content
    assert 'name="quote_pre_refresh_time"' in content
    assert 'name="weekly_auto_advisor_time"' in content


@pytest.mark.django_db
def test_readiness_monitor_page_requires_staff(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/ops/task-monitor/readiness/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_readiness_monitor_page_configure_schedule_action(client, staff_user):
    client.force_login(staff_user)

    with patch(
        "apps.task_monitor.interface.page_views.configure_readiness_schedule",
        return_value={
            "executed_commands": [
                "setup_decision_quote_refresh",
                "setup_personal_readiness_daily",
                "setup_auto_advisor_weekly_report",
            ],
            "output_lines": [],
            "quote_pre_refresh_time": "15:35",
            "daily_evidence_time": "16:10",
            "weekly_auto_advisor_time": "17:30",
        },
    ) as mock_configure:
        response = client.post(
            "/ops/task-monitor/readiness/",
            data={
                "action": "configure_readiness_schedule",
                "quote_pre_refresh_time": "15:35",
                "daily_evidence_time": "16:10",
                "weekly_auto_advisor_time": "17:30",
            },
            follow=False,
        )

    assert response.status_code == 302
    assert response["Location"].endswith("/ops/task-monitor/readiness/")
    mock_configure.assert_called_once_with(
        quote_pre_refresh_time="15:35",
        daily_evidence_time="16:10",
        weekly_auto_advisor_time="17:30",
    )


@pytest.mark.django_db
def test_scheduler_console_bootstrap_action_calls_initializer(client, staff_user):
    client.force_login(staff_user)

    with patch(
        "apps.task_monitor.interface.page_views.bootstrap_scheduler_defaults",
        return_value={"executed_commands": ["init_scheduler_defaults"], "output_lines": []},
    ) as mock_bootstrap:
        response = client.post(
            "/ops/task-monitor/",
            data={"action": "bootstrap_defaults"},
            follow=False,
        )

    assert response.status_code == 302
    assert response["Location"].endswith("/ops/task-monitor/")
    mock_bootstrap.assert_called_once_with()


@pytest.mark.django_db
def test_scheduler_console_configure_readiness_schedule_action(client, staff_user):
    client.force_login(staff_user)

    with patch(
        "apps.task_monitor.interface.page_views.configure_readiness_schedule",
        return_value={
            "executed_commands": [
                "setup_decision_quote_refresh",
                "setup_personal_readiness_daily",
                "setup_auto_advisor_weekly_report",
            ],
            "output_lines": [],
            "quote_pre_refresh_time": "15:35",
            "daily_evidence_time": "16:10",
            "weekly_auto_advisor_time": "17:30",
        },
    ) as mock_configure:
        response = client.post(
            "/ops/task-monitor/",
            data={
                "action": "configure_readiness_schedule",
                "quote_pre_refresh_time": "15:35",
                "daily_evidence_time": "16:10",
                "weekly_auto_advisor_time": "17:30",
            },
            follow=False,
        )

    assert response.status_code == 302
    assert response["Location"].endswith("/ops/task-monitor/")
    mock_configure.assert_called_once_with(
        quote_pre_refresh_time="15:35",
        daily_evidence_time="16:10",
        weekly_auto_advisor_time="17:30",
    )


@pytest.mark.django_db
def test_readiness_monitor_json_requires_staff(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/ops/task-monitor/readiness-monitor.json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_readiness_monitor_json_returns_daily_gate(client, staff_user):
    client.force_login(staff_user)

    with patch(
        "apps.task_monitor.interface.page_views.get_readiness_monitor_context",
        return_value=_readiness_monitor_payload(),
    ) as mock_context:
        response = client.get("/ops/task-monitor/readiness-monitor.json?strict_runtime=1")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["daily_state"]["code"] == "latest_closed_day_accepted"
    assert payload["monitor_gate"]["ok"] is True
    assert payload["window"]["accepted_days"] == 4
    assert payload["window"]["remaining_days"] == 16
    assert payload["data_coverage"]["domains"]["price"]["covered_count"] == 304
    assert payload["data_coverage"]["universe_quality"]["board_counts"]["bse"] == 200
    assert payload["operator_surfaces"]["ai_capability"]["mcp_tools"]["total"] == 365
    assert payload["operator_surfaces"]["terminal"]["tui_metadata"]["screens"] == 37
    mock_context.assert_called_once_with(strict_runtime=True)
