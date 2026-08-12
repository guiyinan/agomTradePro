"""Outcome contracts for destructive Policy Celery maintenance tasks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.policy.application import tasks


def _assert_cleanup_counts(
    payload: dict[str, object],
    *,
    outcome: str,
    succeeded: int,
    failed: int,
    deleted: int,
) -> None:
    assert payload["outcome"] == outcome
    assert payload["success"] is (outcome in {"success", "noop"})
    assert payload["requested_operation_count"] == 1
    assert payload["succeeded_operation_count"] == succeeded
    assert payload["failed_operation_count"] == failed
    assert payload["stored_record_count"] == 0
    assert payload["deleted_record_count"] == deleted


def test_policy_cleanup_tasks_reject_invalid_input_with_failed_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid bounds fail before any destructive repository lookup."""

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

    payloads = (
        tasks.cleanup_old_policy_logs.run(days_to_keep=True),
        tasks.cleanup_old_rss_logs.run(days_to_keep=0),
        tasks.cleanup_old_audit_queues.run(days_to_keep=-1),
    )

    for payload in payloads:
        _assert_cleanup_counts(
            payload,
            outcome="failed",
            succeeded=0,
            failed=1,
            deleted=0,
        )
        assert payload["error_type"] == "input"


def test_policy_cleanup_tasks_report_all_success_and_exact_deleted_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed destructive operation reports operation and deletion units separately."""

    monkeypatch.setattr(
        tasks,
        "get_current_policy_repository",
        lambda: SimpleNamespace(delete_events_before=lambda cutoff: 3),
    )
    monkeypatch.setattr(
        tasks,
        "get_rss_repository",
        lambda: SimpleNamespace(cleanup_old_logs=lambda days: 4),
    )
    monkeypatch.setattr(
        tasks,
        "get_workbench_repository",
        lambda: SimpleNamespace(delete_reviewed_queue_before=lambda cutoff: 2),
    )

    payloads = (
        (tasks.cleanup_old_policy_logs.run(30), 3),
        (tasks.cleanup_old_rss_logs.run(30), 4),
        (tasks.cleanup_old_audit_queues.run(30), 2),
    )

    for payload, deleted in payloads:
        _assert_cleanup_counts(
            payload,
            outcome="success",
            succeeded=1,
            failed=0,
            deleted=deleted,
        )


def test_policy_cleanup_tasks_report_zero_output_as_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid cleanup with no matching rows is a successful no-op, not fake output."""

    monkeypatch.setattr(
        tasks,
        "get_current_policy_repository",
        lambda: SimpleNamespace(delete_events_before=lambda cutoff: 0),
    )
    monkeypatch.setattr(
        tasks,
        "get_rss_repository",
        lambda: SimpleNamespace(cleanup_old_logs=lambda days: 0),
    )
    monkeypatch.setattr(
        tasks,
        "get_workbench_repository",
        lambda: SimpleNamespace(delete_reviewed_queue_before=lambda cutoff: 0),
    )

    payloads = (
        tasks.cleanup_old_policy_logs.run(30),
        tasks.cleanup_old_rss_logs.run(30),
        tasks.cleanup_old_audit_queues.run(30),
    )

    for payload in payloads:
        _assert_cleanup_counts(
            payload,
            outcome="noop",
            succeeded=1,
            failed=0,
            deleted=0,
        )


def test_policy_cleanup_tasks_report_complete_failure_without_deleted_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repository failures remain business failures with zero claimed deletion."""

    def fail(*args: object) -> int:
        del args
        raise RuntimeError("cleanup unavailable")

    monkeypatch.setattr(
        tasks,
        "get_current_policy_repository",
        lambda: SimpleNamespace(delete_events_before=fail),
    )
    monkeypatch.setattr(
        tasks,
        "get_rss_repository",
        lambda: SimpleNamespace(cleanup_old_logs=fail),
    )
    monkeypatch.setattr(
        tasks,
        "get_workbench_repository",
        lambda: SimpleNamespace(delete_reviewed_queue_before=fail),
    )

    payloads = (
        tasks.cleanup_old_policy_logs.run(30),
        tasks.cleanup_old_rss_logs.run(30),
        tasks.cleanup_old_audit_queues.run(30),
    )

    for payload in payloads:
        _assert_cleanup_counts(
            payload,
            outcome="failed",
            succeeded=0,
            failed=1,
            deleted=0,
        )
        assert payload["error"] == "cleanup unavailable"
