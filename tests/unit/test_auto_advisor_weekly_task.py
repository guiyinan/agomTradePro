import io
from datetime import date

import pytest
from django.core.management import call_command
from django_celery_beat.models import PeriodicTask

from apps.dashboard.application import tasks as dashboard_tasks
from apps.dashboard.application.tasks import generate_auto_advisor_weekly_reports_task


def test_generate_auto_advisor_weekly_reports_for_active_targets(monkeypatch):
    class _User:
        id = 7
        is_authenticated = True
        is_staff = False
        is_superuser = False

    monkeypatch.setattr(
        dashboard_tasks,
        "list_active_account_targets",
        lambda: [
            {"account_id": 101, "user_id": 7},
            {"account_id": 101, "user_id": 7},
        ],
    )
    monkeypatch.setattr(dashboard_tasks, "get_application_user_by_id", lambda user_id: _User())

    def _fake_report(*, account_id, user, as_of):
        return {
            "status": "ok",
            "account": {"id": int(account_id)},
            "week": {"as_of": as_of.isoformat()},
            "user_id": user.id,
        }

    monkeypatch.setattr(
        dashboard_tasks,
        "build_auto_advisor_weekly_report_payload",
        _fake_report,
    )
    monkeypatch.setattr(
        dashboard_tasks,
        "persist_auto_advisor_weekly_report_outputs",
        lambda *, user, report_payload: {"report": {"id": 1}},
    )

    payload = generate_auto_advisor_weekly_reports_task.run(as_of="2026-06-26")

    assert payload["status"] == "ok"
    assert payload["as_of"] == "2026-06-26"
    assert payload["target_count"] == 1
    assert payload["generated_count"] == 1
    assert payload["failed_count"] == 0
    assert payload["reports"][0]["account_id"] == 101
    assert payload["reports"][0]["report"]["week"]["as_of"] == "2026-06-26"
    assert payload["reports"][0]["persisted"]["report"]["id"] == 1


def test_generate_auto_advisor_weekly_reports_filters_user_accounts(monkeypatch):
    class _User:
        id = 3
        is_authenticated = True
        is_staff = False
        is_superuser = False

    monkeypatch.setattr(
        dashboard_tasks,
        "list_dashboard_account_payloads",
        lambda user_id: [
            {"id": 11, "is_active": True},
            {"id": 12, "is_active": True},
            {"id": 13, "is_active": False},
        ],
    )
    monkeypatch.setattr(dashboard_tasks, "get_application_user_by_id", lambda user_id: _User())
    monkeypatch.setattr(
        dashboard_tasks,
        "build_auto_advisor_weekly_report_payload",
        lambda *, account_id, user, as_of: {
            "status": "ok",
            "account": {"id": int(account_id)},
            "week": {"as_of": as_of.isoformat()},
        },
    )
    monkeypatch.setattr(
        dashboard_tasks,
        "persist_auto_advisor_weekly_report_outputs",
        lambda *, user, report_payload: {"report": {"id": int(report_payload["account"]["id"])}},
    )

    payload = generate_auto_advisor_weekly_reports_task.run(
        user_id=3,
        account_ids=[12, 13],
        as_of=date(2026, 6, 26).isoformat(),
    )

    assert payload["generated_count"] == 2
    assert [row["account_id"] for row in payload["reports"]] == [12, 13]


def test_generate_auto_advisor_weekly_reports_records_missing_user(monkeypatch):
    monkeypatch.setattr(
        dashboard_tasks,
        "list_active_account_targets",
        lambda: [{"account_id": 101, "user_id": 404}],
    )
    monkeypatch.setattr(dashboard_tasks, "get_application_user_by_id", lambda user_id: None)

    payload = generate_auto_advisor_weekly_reports_task.run(as_of="2026-06-26")

    assert payload["status"] == "partial"
    assert payload["generated_count"] == 0
    assert payload["failed_count"] == 1
    assert payload["errors"][0]["error"] == "user_not_found"


@pytest.mark.django_db
def test_setup_auto_advisor_weekly_report_creates_periodic_task():
    out = io.StringIO()

    call_command(
        "setup_auto_advisor_weekly_report",
        hour=18,
        minute=5,
        day_of_week="fri",
        user_id=7,
        account_ids="101,102",
        stdout=out,
    )

    task = PeriodicTask.objects.get(name="dashboard-auto-advisor-weekly-report")
    assert task.task == "dashboard.generate_auto_advisor_weekly_reports"
    assert task.enabled is True
    assert task.kwargs == '{"user_id": 7, "account_ids": [101, 102]}'
    assert task.crontab is not None
    assert task.crontab.hour == "18"
    assert task.crontab.minute == "5"
    assert task.crontab.day_of_week == "fri"
    assert "Auto-advisor weekly report task configured" in out.getvalue()
