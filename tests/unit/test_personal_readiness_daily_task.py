from __future__ import annotations

from datetime import date
from pathlib import Path

from apps.operational_readiness.application import tasks as canonical_task_module
from apps.task_monitor.application import tasks as task_module
from core.celery import app as celery_app


def test_readiness_canonical_and_legacy_task_names_remain_registered_contracts():
    assert canonical_task_module.run_personal_readiness_daily_task.name == (
        "apps.operational_readiness.application.tasks." "run_personal_readiness_daily_task"
    )
    assert task_module.run_personal_readiness_daily_task.name == (
        "apps.task_monitor.application.tasks.run_personal_readiness_daily_task"
    )


def test_readiness_canonical_and_legacy_tasks_are_registered_with_celery():
    """Worker task discovery must retain both scheduler and compatibility names."""
    celery_app.loader.import_default_modules()

    assert canonical_task_module.CANONICAL_READINESS_TASK_NAME in celery_app.tasks
    assert canonical_task_module.LEGACY_READINESS_TASK_NAME in celery_app.tasks


def test_personal_readiness_daily_task_calls_runner(monkeypatch):
    captured: dict[str, object] = {}

    def fake_runner(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "status": "ok",
            "validation": {
                "accepted_days": 2,
                "remaining_days": 18,
            },
        }

    monkeypatch.setattr(task_module, "run_personal_readiness_daily", fake_runner)

    payload = task_module.run_personal_readiness_daily_task.run(
        target_date="2026-07-01",
        user_id=7,
        repair_accounts=False,
        run_workspace_refresh=True,
        include_weekly_advisor=True,
    )

    kwargs = captured["kwargs"]
    assert kwargs["target_date"] == date(2026, 7, 1)
    assert kwargs["user_id"] == 7
    assert kwargs["output_dir"] == Path("var/readiness-evidence")
    assert kwargs["calendar_source"] == "auto"
    assert kwargs["repair_accounts"] is False
    assert kwargs["run_workspace_refresh"] is True
    assert kwargs["include_weekly_advisor"] is True
    assert kwargs["persist_risk_report"] is True
    assert kwargs["allow_unclosed_target_date"] is False
    assert kwargs["trigger_source"] == "scheduler"
    assert kwargs["trigger_task_name"] == task_module.run_personal_readiness_daily_task.name
    assert "trigger_task_id" in kwargs
    assert payload["status"] == "ok"
    assert payload["validation"]["accepted_days"] == 2


def test_personal_readiness_daily_task_passes_celery_request_id(monkeypatch):
    captured: dict[str, object] = {}

    def fake_runner(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "status": "ok",
            "validation": {
                "accepted_days": 3,
                "remaining_days": 17,
            },
        }

    monkeypatch.setattr(task_module, "run_personal_readiness_daily", fake_runner)

    result = task_module.run_personal_readiness_daily_task.apply(
        kwargs={"target_date": "2026-07-02"},
        task_id="scheduled-readiness-task-20260702",
    )

    kwargs = captured["kwargs"]
    assert kwargs["target_date"] == date(2026, 7, 2)
    assert kwargs["trigger_source"] == "scheduler"
    assert kwargs["trigger_task_id"] == "scheduled-readiness-task-20260702"
    assert kwargs["trigger_task_name"] == task_module.run_personal_readiness_daily_task.name
    assert result.get()["validation"]["accepted_days"] == 3


def test_personal_readiness_daily_task_can_allow_unclosed_target_date(monkeypatch):
    captured: dict[str, object] = {}

    def fake_runner(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "status": "ok",
            "validation": {
                "accepted_days": 0,
                "remaining_days": 20,
            },
        }

    monkeypatch.setattr(task_module, "run_personal_readiness_daily", fake_runner)

    payload = task_module.run_personal_readiness_daily_task.run(
        target_date="2026-07-01",
        allow_unclosed_target_date=True,
    )

    kwargs = captured["kwargs"]
    assert kwargs["target_date"] == date(2026, 7, 1)
    assert kwargs["allow_unclosed_target_date"] is True
    assert kwargs["trigger_source"] == "scheduler"
    assert kwargs["trigger_task_name"] == task_module.run_personal_readiness_daily_task.name
    assert payload["status"] == "ok"


def test_personal_readiness_daily_task_strict_daily_raises_on_non_ok(monkeypatch):
    def fake_runner(**kwargs):
        return {"status": "warning"}

    monkeypatch.setattr(task_module, "run_personal_readiness_daily", fake_runner)

    try:
        task_module.run_personal_readiness_daily_task.run(
            target_date="2026-07-01",
            strict_daily=True,
        )
    except RuntimeError as exc:
        assert "warning" in str(exc)
    else:
        raise AssertionError("strict daily task should raise on non-ok payload")
