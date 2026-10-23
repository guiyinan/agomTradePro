"""Task Monitor and metrics consume Account outcomes independently of Celery state."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.task_monitor.application.dtos import project_task_business_result
from apps.task_monitor.application.tasks import _resolve_terminal_status, _serialize_task_result
from apps.task_monitor.domain.entities import TaskStatus
from core.metrics import track_celery_task


def _exit_observation(*, triggered: bool) -> SimpleNamespace:
    """Build the existing task-result shape needed by risk count summarization."""

    return SimpleNamespace(
        triggered=triggered,
        check_status="evaluated",
        execution_status="blocked" if triggered else "not_triggered",
    )


@pytest.mark.parametrize(
    ("observations", "expected_outcome", "requested", "succeeded", "failed"),
    [
        ([_exit_observation(triggered=True)], "blocked", 1, 0, 1),
        (
            [_exit_observation(triggered=True), _exit_observation(triggered=False)],
            "partial",
            2,
            1,
            1,
        ),
    ],
)
def test_monitor_and_metrics_consume_account_exit_outcome(
    monkeypatch: pytest.MonkeyPatch,
    observations: list[SimpleNamespace],
    expected_outcome: str,
    requested: int,
    succeeded: int,
    failed: int,
) -> None:
    """Blocked and partial Account results stay visible after successful transport."""

    from apps.account.application import tasks as account_tasks

    monkeypatch.setattr(
        account_tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: observations,
        ),
    )
    monkeypatch.setattr(account_tasks, "_send_stop_loss_notifications", lambda *_args: None)
    result = account_tasks.check_stop_loss_task.run(user_id=7)

    status = _resolve_terminal_status(state="SUCCESS", retval=result)
    projection = project_task_business_result(_serialize_task_result(result))

    assert status is TaskStatus.SUCCESS
    assert projection.outcome == expected_outcome
    assert projection.business_success is False
    assert (projection.requested, projection.succeeded, projection.failed, projection.stored) == (
        requested,
        succeeded,
        failed,
        0,
    )
    assert projection.stored_count_unit == "confirmed_simulated_trade_receipt"
    assert result["executed_count"] == 0
    assert result["stored"] == 0

    @track_celery_task
    def monitored_exit_task() -> dict[str, object]:
        return result

    with patch("core.metrics.record_celery_task") as record_metric:
        monitored_exit_task()

    assert record_metric.call_args.kwargs["status"] == expected_outcome


def test_monitor_preserves_unknown_stage_counts_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown Account stage results reach Task Monitor with null denominators."""

    from apps.account.application import tasks as account_tasks

    monkeypatch.setattr(
        account_tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("provider outcome unknown")
            ),
        ),
    )
    monkeypatch.setattr(account_tasks, "record_exception", lambda *_args, **_kwargs: None)
    result = account_tasks.check_stop_loss_task.run(user_id=7)

    status = _resolve_terminal_status(state="SUCCESS", retval=result)
    projection = project_task_business_result(_serialize_task_result(result))

    assert status is TaskStatus.FAILURE
    assert projection.outcome == "failed"
    assert projection.business_success is False
    assert projection.counts_unavailable is True
    assert projection.stored_count_unit == "confirmed_simulated_trade_receipt"
    assert (projection.requested, projection.succeeded, projection.failed, projection.stored) == (
        None,
        None,
        None,
        None,
    )
