from __future__ import annotations

from datetime import date

from apps.task_monitor.management.commands import (
    simulate_personal_readiness_checkpoints as command_module,
)


def test_simulate_personal_readiness_checkpoints_uses_injected_times(monkeypatch):
    monkeypatch.setattr(
        command_module.status_command,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "name": "personal-readiness-daily-evidence",
            "schedule": {
                "minute": "10",
                "hour": "16",
                "timezone": "Asia/Shanghai",
            },
        },
    )
    monkeypatch.setattr(
        command_module.status_command,
        "_collect_quote_pre_readiness_scheduler_status",
        lambda: {
            "status": "ok",
            "name": "decision-quote-pre-readiness-refresh",
            "schedule": {
                "minute": "35",
                "hour": "15",
                "timezone": "Asia/Shanghai",
            },
            "run_metadata": {
                "last_run_at": "2026-07-02T15:35:00+08:00",
                "total_run_count": 2,
            },
        },
    )

    payload = command_module.simulate_checkpoints(
        target_date=date(2026, 7, 3),
        times=(
            "2026-07-03T15:50:00+08:00",
            "2026-07-03T16:20:00+08:00",
            "2026-07-03T17:20:00+08:00",
            "2026-07-03T17:45:00+08:00",
        ),
    )

    assert payload["mode"] == "simulation"
    assert payload["mutates_state"] is False
    assert payload["generates_evidence"] is False
    assert len(payload["checkpoints"]) == 4
    assert (
        payload["checkpoints"][0]["quote_pre_readiness"]["due_status"]
        == "grace_period"
    )
    assert payload["checkpoints"][1]["daily_readiness"]["due_status"] == "grace_period"
    assert payload["checkpoints"][2]["weekly_auto_advisor"] == {
        "due": False,
        "reason": "weekly_report_schedule_not_due_yet",
        "scheduled_for": "2026-07-03T17:30:00+08:00",
    }
    assert payload["checkpoints"][3]["weekly_auto_advisor"] == {
        "due": True,
        "reason": "weekly_report_schedule_due",
        "scheduled_for": "2026-07-03T17:30:00+08:00",
    }
