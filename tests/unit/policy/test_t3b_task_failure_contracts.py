"""T3B Policy task contracts for retry, input, and partial-failure outcomes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from celery.exceptions import MaxRetriesExceededError

from apps.policy.application import tasks
from core.exceptions import DataFetchError


def _raise(exc: Exception):
    raise exc


@pytest.mark.parametrize(
    ("exception", "expected_error_type"),
    [
        (ValueError("invalid state"), "business_logic"),
        (DataFetchError("provider offline"), "retry_exhausted"),
        (RuntimeError("unexpected"), "retry_exhausted"),
    ],
)
def test_policy_status_task_distinguishes_business_and_exhausted_retry_failures(
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    expected_error_type: str,
) -> None:
    """Status checks retry external failures but serialize non-retryable business errors."""
    monkeypatch.setattr(
        tasks,
        "GetPolicyStatusUseCase",
        lambda event_store: SimpleNamespace(execute=lambda day: _raise(exception)),
    )
    monkeypatch.setattr(
        tasks,
        "get_current_policy_repository",
        lambda: SimpleNamespace(),
    )
    if expected_error_type == "business_logic":
        result = tasks.check_policy_status_alert.run("2026-07-24")
        assert result["error_type"] == expected_error_type
        assert result["error"] == "invalid state"
        assert result["outcome"] == "failed"
        return

    monkeypatch.setattr(
        tasks.check_policy_status_alert,
        "retry",
        lambda **kwargs: _raise(MaxRetriesExceededError()),
    )
    with pytest.raises(MaxRetriesExceededError):
        tasks.check_policy_status_alert.run("2026-07-24")


def test_policy_transition_and_cleanup_tasks_serialize_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduled maintenance publishes stable failures for unexpected repository errors."""
    monkeypatch.setattr(
        tasks,
        "get_current_policy_repository",
        lambda: SimpleNamespace(
            get_events_in_range=lambda *args: _raise(RuntimeError("transition crashed")),
            delete_events_before=lambda cutoff: _raise(RuntimeError("cleanup crashed")),
        ),
    )
    transition = tasks.monitor_policy_transitions.run()
    assert transition["status"] == "error"
    assert transition["outcome"] == "failed"
    assert transition["error"] == "transition crashed"
    cleanup = tasks.cleanup_old_policy_logs.run(30)
    assert cleanup["status"] == "error"
    assert cleanup["outcome"] == "failed"
    assert cleanup["error"] == "cleanup crashed"


def test_fetch_rss_task_validates_source_and_survives_classifier_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RSS task rejects bool IDs and falls back to keyword classification."""
    invalid = tasks.fetch_rss_sources.run(source_id=True)
    assert invalid["error_type"] == "input"
    assert invalid["outcome"] == "failed"

    from apps.policy.application import use_cases

    captured: dict[str, object] = {}

    class _FetchUseCase:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def execute(self, input_dto: object) -> SimpleNamespace:
            return SimpleNamespace(
                sources_processed=2,
                total_items=3,
                new_policy_events=1,
                errors=[],
            )

    policy_repo = SimpleNamespace(get_category_stats=lambda: {"macro": 1})
    monkeypatch.setattr(tasks, "get_rss_repository", lambda: SimpleNamespace())
    monkeypatch.setattr(tasks, "get_current_policy_repository", lambda: policy_repo)
    monkeypatch.setattr(
        tasks,
        "get_ai_policy_classifier",
        lambda: _raise(RuntimeError("AI config invalid")),
    )
    monkeypatch.setattr(use_cases, "FetchRSSUseCase", _FetchUseCase)
    result = tasks.fetch_rss_sources.run(source_id=None)
    assert result["status"] == "success"
    assert result["outcome"] == "success"
    assert result["requested_source_count"] == 2
    assert result["stored_record_count"] == 1
    assert result["new_events"] == 1
    assert captured["ai_classifier"] is None


def test_fetch_rss_task_propagates_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RSS fetch failure remains a failed task after its retry budget is exhausted."""
    monkeypatch.setattr(
        tasks,
        "get_rss_repository",
        lambda: _raise(RuntimeError("RSS repository offline")),
    )
    monkeypatch.setattr(
        tasks.fetch_rss_sources,
        "retry",
        lambda **kwargs: _raise(MaxRetriesExceededError()),
    )
    with pytest.raises(MaxRetriesExceededError):
        tasks.fetch_rss_sources.run()


def test_fetch_rss_task_reports_partial_and_zero_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source-level errors remain partial and an empty enabled set remains a no-op."""

    from apps.policy.application import use_cases

    responses = [
        SimpleNamespace(
            sources_processed=1,
            total_items=2,
            new_policy_events=1,
            errors=["source-2 unavailable"],
        ),
        SimpleNamespace(
            sources_processed=0,
            total_items=0,
            new_policy_events=0,
            errors=[],
        ),
    ]

    class _FetchUseCase:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def execute(self, input_dto: object) -> SimpleNamespace:
            del input_dto
            return responses.pop(0)

    monkeypatch.setattr(tasks, "get_rss_repository", lambda: SimpleNamespace())
    monkeypatch.setattr(
        tasks,
        "get_current_policy_repository",
        lambda: SimpleNamespace(get_category_stats=lambda: {"macro": 1}),
    )
    monkeypatch.setattr(tasks, "get_ai_policy_classifier", lambda: None)
    monkeypatch.setattr(use_cases, "FetchRSSUseCase", _FetchUseCase)

    partial = tasks.fetch_rss_sources.run()
    empty = tasks.fetch_rss_sources.run()

    assert partial["outcome"] == "partial"
    assert partial["requested_source_count"] == 2
    assert partial["succeeded_source_count"] == 1
    assert partial["failed_source_count"] == 1
    assert empty["outcome"] == "noop"
    assert empty["requested_source_count"] == 0


def test_policy_maintenance_tasks_keep_repository_errors_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup, assignment, and summary failures never report success."""
    monkeypatch.setattr(
        tasks,
        "get_rss_repository",
        lambda: SimpleNamespace(
            cleanup_old_logs=lambda days: _raise(RuntimeError("RSS cleanup failed"))
        ),
    )
    rss_cleanup = tasks.cleanup_old_rss_logs.run(30)
    assert rss_cleanup["status"] == "error"
    assert rss_cleanup["outcome"] == "failed"
    assert rss_cleanup["error"] == "RSS cleanup failed"

    monkeypatch.setattr(
        tasks,
        "get_workbench_repository",
        lambda: SimpleNamespace(
            list_unassigned_audit_queue_ids=lambda: _raise(RuntimeError("assignment query failed")),
            delete_reviewed_queue_before=lambda cutoff: _raise(
                RuntimeError("audit cleanup failed")
            ),
            get_global_heat_sentiment=lambda: _raise(RuntimeError("gate source failed")),
        ),
    )
    assignment = tasks.auto_assign_pending_audits.run(10)
    assert assignment["assigned"] == 0
    assert assignment["outcome"] == "failed"
    assert assignment["error"] == "assignment query failed"
    audit_cleanup = tasks.cleanup_old_audit_queues.run(30)
    assert audit_cleanup["status"] == "error"
    assert audit_cleanup["outcome"] == "failed"
    assert audit_cleanup["error"] == "audit cleanup failed"
    gate = tasks.refresh_gate_constraints_task.run()
    assert gate["status"] == "error"
    assert gate["outcome"] == "failed"
    assert gate["error"] == "gate source failed"


def test_signal_reevaluation_rejects_non_string_event_dates() -> None:
    """Celery payload validation rejects non-string dates before runtime lookups."""
    result = tasks.trigger_signal_reevaluation.run(2, 20260724)
    assert result["error_type"] == "input"
    assert result["error"] == "event_date 必须是 YYYY-MM-DD 字符串"
