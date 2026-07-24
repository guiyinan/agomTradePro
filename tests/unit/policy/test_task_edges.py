"""Policy scheduled-task aggregation, assignment, and alert contracts."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from django.db import DatabaseError

from apps.policy.application import tasks
from apps.policy.domain.entities import PolicyEvent, PolicyLevel
from core.exceptions import DataFetchError


def _event(level: PolicyLevel, day: int) -> PolicyEvent:
    return PolicyEvent(
        event_date=date(2026, 7, day),
        level=level,
        title=f"{level.value} event",
        description="contract",
        evidence_url="https://evidence.test",
    )


def test_policy_status_transition_cleanup_and_notification_tasks(monkeypatch) -> None:
    """Status monitoring emits alerts/transitions and cleanup returns deleted counts."""
    events = [_event(PolicyLevel.P1, 23), _event(PolicyLevel.P2, 24)]
    repo = SimpleNamespace(
        get_events_in_range=lambda start, end: events,
        delete_events_before=lambda cutoff: 3,
    )
    monkeypatch.setattr(tasks, "get_current_policy_repository", lambda: repo)
    sent: list[object] = []
    monkeypatch.setattr(tasks, "_send_transition_summary", lambda changes: sent.extend(changes))
    transition = tasks.monitor_policy_transitions.run()
    assert transition["transitions_found"] == 1
    assert sent[0]["from"] == "P1" and sent[0]["to"] == "P2"
    assert tasks.cleanup_old_policy_logs.run(30)["deleted_count"] == 3

    status = SimpleNamespace(current_level=PolicyLevel.P2, latest_event=events[-1])
    monkeypatch.setattr(
        tasks,
        "GetPolicyStatusUseCase",
        lambda event_store: SimpleNamespace(execute=lambda as_of_date: status),
    )
    alerts: list[PolicyLevel] = []
    monkeypatch.setattr(
        tasks,
        "_send_policy_alert",
        lambda level, event, status: alerts.append(level),
    )
    result = tasks.check_policy_status_alert.run("2026-07-24")
    assert result["level"] == "P2"
    assert alerts == [PolicyLevel.P2]


def test_rss_cleanup_assignment_summary_and_sla_tasks(monkeypatch) -> None:
    """RSS/workbench tasks assign within capacity and report SLA evidence."""
    rss_repo = SimpleNamespace(cleanup_old_logs=lambda days: 4)
    monkeypatch.setattr(tasks, "get_rss_repository", lambda: rss_repo)
    assert tasks.cleanup_old_rss_logs.run(90)["deleted_count"] == 4

    assignments: list[tuple[int, int]] = []
    workbench = SimpleNamespace(
        list_unassigned_audit_queue_ids=lambda: [1, 2, 3],
        list_staff_auditor_ids=lambda: [10, 20],
        get_pending_assignment_counts=lambda ids: {10: 0, 20: 1},
        assign_audit_queue_item=lambda queue_id, auditor_id, assigned_at: (
            assignments.append((queue_id, auditor_id)) or True
        ),
        delete_reviewed_queue_before=lambda cutoff: 2,
        get_daily_policy_summary=lambda today: {"status": "success", "events": 5},
        get_ingestion_config=lambda: SimpleNamespace(p23_sla_hours=2, normal_sla_hours=24),
        get_sla_exceeded_breakdown=lambda **kwargs: {
            "p23_exceeded": 2,
            "normal_exceeded": 1,
            "total_exceeded": 3,
        },
    )
    monkeypatch.setattr(tasks, "get_workbench_repository", lambda: workbench)
    assigned = tasks.auto_assign_pending_audits.run(max_per_user=2)
    assert assigned["assigned"] == 3
    assert assigned["remaining"] == 0
    assert tasks.cleanup_old_audit_queues.run()["deleted_count"] == 2
    assert tasks.generate_daily_policy_summary.run()["events"] == 5

    sla_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        tasks,
        "_get_notification_service",
        lambda: SimpleNamespace(send_sla_alert=lambda p23, normal: sla_calls.append((p23, normal))),
    )
    sla = tasks.monitor_sla_exceeded_task.run()
    assert sla["total_exceeded"] == 3
    assert sla_calls == [(2, 1)]


def test_gate_refresh_signal_reevaluation_and_no_auditor_paths(monkeypatch) -> None:
    """Gate refresh and signal reevaluation serialize decisions and empty staffing."""
    thresholds = SimpleNamespace(
        heat_l1_threshold=30,
        heat_l2_threshold=60,
        heat_l3_threshold=85,
        sentiment_l1_threshold=-0.3,
        sentiment_l2_threshold=-0.6,
        sentiment_l3_threshold=-0.8,
    )
    workbench = SimpleNamespace(
        get_global_heat_sentiment=lambda: (70.0, -0.2),
        get_gate_config=lambda scope: thresholds,
        list_unassigned_audit_queue_ids=lambda: [1, 2],
        list_staff_auditor_ids=lambda: [],
    )
    monkeypatch.setattr(tasks, "get_workbench_repository", lambda: workbench)
    gate = tasks.refresh_gate_constraints_task.run()
    assert gate["status"] == "success"
    assert gate["gate_level"]
    assert tasks.auto_assign_pending_audits.run()["remaining"] == 2

    from apps.regime.application import current_regime

    monkeypatch.setattr(
        current_regime,
        "resolve_current_regime",
        lambda: SimpleNamespace(dominant_regime="Recovery", confidence=0.8),
    )
    monkeypatch.setattr(
        tasks,
        "reevaluate_signals_for_policy_change",
        lambda **kwargs: SimpleNamespace(
            total_count=4,
            rejected_count=1,
            rejected_signal_ids=["signal-1"],
        ),
    )
    reevaluated = tasks.trigger_signal_reevaluation.run(2, "2026-07-24")
    assert reevaluated["rejected_count"] == 1
    assert reevaluated["current_regime"] == "Recovery"


def test_policy_scheduled_tasks_report_repository_and_runtime_failures(monkeypatch) -> None:
    """Expected data failures are serialized while notification helpers fail closed."""
    monkeypatch.setattr(
        tasks,
        "get_current_policy_repository",
        lambda: SimpleNamespace(
            get_events_in_range=lambda *args: (_ for _ in ()).throw(DataFetchError("offline")),
            delete_events_before=lambda cutoff: (_ for _ in ()).throw(DatabaseError("locked")),
        ),
    )
    transition = tasks.monitor_policy_transitions.run()
    assert transition["error_type"] == "data_fetch"
    cleanup = tasks.cleanup_old_policy_logs.run(30)
    assert cleanup["error_type"] == "database"

    monkeypatch.setattr(
        tasks,
        "get_workbench_repository",
        lambda: SimpleNamespace(
            get_daily_policy_summary=lambda today: (_ for _ in ()).throw(
                RuntimeError("summary failed")
            ),
            get_ingestion_config=lambda: (_ for _ in ()).throw(RuntimeError("config failed")),
            get_global_heat_sentiment=lambda: (None, None),
            get_gate_config=lambda scope: None,
        ),
    )
    assert tasks.generate_daily_policy_summary.run()["status"] == "error"
    assert tasks.monitor_sla_exceeded_task.run()["status"] == "error"
    gate = tasks.refresh_gate_constraints_task.run()
    assert gate["message"] == "No gate config or data available"

    monkeypatch.setattr(
        tasks,
        "_get_notification_service",
        lambda: SimpleNamespace(
            send_policy_alert=lambda *args: (_ for _ in ()).throw(RuntimeError("notify failed")),
            send_transition_summary=lambda *args: (_ for _ in ()).throw(
                RuntimeError("notify failed")
            ),
        ),
    )
    event = _event(PolicyLevel.P2, 24)
    tasks._send_policy_alert(PolicyLevel.P2, event, SimpleNamespace())
    tasks._send_transition_summary([{"from": "P1", "to": "P2"}])


@pytest.mark.parametrize(
    ("task", "kwargs"),
    [
        (tasks.cleanup_old_policy_logs, {"days_to_keep": -1}),
        (tasks.cleanup_old_rss_logs, {"days_to_keep": 0}),
        (tasks.cleanup_old_audit_queues, {"days_to_keep": False}),
        (tasks.auto_assign_pending_audits, {"max_per_user": 0}),
    ],
)
def test_policy_destructive_tasks_reject_invalid_bounds_before_repository_access(
    monkeypatch,
    task,
    kwargs,
) -> None:
    monkeypatch.setattr(
        tasks,
        "get_current_policy_repository",
        lambda: pytest.fail("policy repository must not be called"),
    )
    monkeypatch.setattr(
        tasks,
        "get_rss_repository",
        lambda: pytest.fail("RSS repository must not be called"),
    )
    monkeypatch.setattr(
        tasks,
        "get_workbench_repository",
        lambda: pytest.fail("workbench repository must not be called"),
    )

    result = task.run(**kwargs)

    assert result["status"] == "error"
    assert result["error_type"] == "input"


@pytest.mark.parametrize(
    ("new_level", "event_date"),
    [
        (4, "2026-07-24"),
        (True, "2026-07-24"),
        (2, "not-a-date"),
    ],
)
def test_signal_reevaluation_rejects_invalid_policy_context(
    new_level,
    event_date,
) -> None:
    result = tasks.trigger_signal_reevaluation.run(new_level, event_date)

    assert result["status"] == "error"
    assert result["error_type"] == "input"


def test_signal_reevaluation_does_not_swallow_retry(monkeypatch) -> None:
    from apps.regime.application import current_regime

    monkeypatch.setattr(
        current_regime,
        "resolve_current_regime",
        lambda: (_ for _ in ()).throw(RuntimeError("regime unavailable")),
    )
    monkeypatch.setattr(
        tasks.trigger_signal_reevaluation,
        "retry",
        lambda **kwargs: RuntimeError("retry scheduled"),
    )

    with pytest.raises(RuntimeError, match="retry scheduled"):
        tasks.trigger_signal_reevaluation.run(2, "2026-07-24")
