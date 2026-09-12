"""Behavioral branch coverage for Task Monitor domain value objects."""

from datetime import UTC, datetime

from apps.task_monitor.domain.entities import (
    TaskFailureAlert,
    TaskStatistics,
    TaskStatus,
)


def test_non_final_failure_is_a_warning_and_statistics_are_serializable() -> None:
    """A retryable failure warns, while statistics preserve an absent last timestamp."""

    alert = TaskFailureAlert(
        task_id="task-1",
        task_name="signals.refresh",
        exception="provider unavailable",
        traceback=None,
        retries=1,
        max_retries=3,
        is_final_failure=False,
        triggered_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    statistics = TaskStatistics(
        task_name="signals.refresh",
        total_executions=2,
        successful_executions=1,
        failed_executions=1,
        average_runtime=0.5,
        success_rate=0.5,
        last_execution_status=TaskStatus.FAILURE,
        last_execution_at=None,
    )

    assert alert.should_alert() is False
    assert alert.get_severity() == "warning"
    assert statistics.to_dict() == {
        "task_name": "signals.refresh",
        "total_executions": 2,
        "successful_executions": 1,
        "failed_executions": 1,
        "average_runtime": 0.5,
        "success_rate": 0.5,
        "last_execution_status": "failure",
        "last_execution_at": None,
    }
