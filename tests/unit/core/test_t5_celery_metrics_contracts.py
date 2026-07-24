"""T5 Celery signal, queue, and decorator metric contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from celery.exceptions import Retry, SoftTimeLimitExceeded

from core import celery_metrics, metrics


class _Metric:
    def __init__(self) -> None:
        self.labels_seen: list[dict[str, object]] = []
        self.values: list[tuple[str, object]] = []

    def labels(self, **kwargs: object) -> _Metric:
        self.labels_seen.append(kwargs)
        return self

    def inc(self) -> None:
        self.values.append(("inc", 1))

    def observe(self, value: object) -> None:
        self.values.append(("observe", value))

    def set(self, value: object) -> None:
        self.values.append(("set", value))


@pytest.fixture
def metric_spies(monkeypatch: pytest.MonkeyPatch) -> dict[str, _Metric]:
    names = [
        "celery_task_total",
        "celery_task_duration_seconds",
        "celery_task_retry_total",
        "celery_active_workers",
        "celery_queue_length",
    ]
    spies = {name: _Metric() for name in names}
    for name, spy in spies.items():
        monkeypatch.setattr(metrics, name, spy)
    celery_metrics._task_start_times.clear()
    return spies


def test_signal_handlers_record_success_failure_retry_and_revoke(
    metric_spies: dict[str, _Metric],
) -> None:
    task = SimpleNamespace(name="fixture.task")
    celery_metrics.task_prerun_handler(task_id="task-1")
    celery_metrics.task_postrun_handler(task_id="task-1", task=task, retval={"status": "ok"})
    celery_metrics.task_postrun_handler(task_id="missing", task=task, retval=RuntimeError("failed"))

    request = SimpleNamespace(task="fixture.task", id="task-1")
    celery_metrics.task_retry_handler(request=request, reason=RuntimeError("retry"))
    celery_metrics.task_retry_handler(request=request, reason="backoff")
    celery_metrics.task_retry_handler(
        request=request,
        einfo=SimpleNamespace(exception=ValueError("invalid")),
    )
    celery_metrics.task_failure_handler(
        sender=task,
        task_id="task-1",
        exception=RuntimeError("failed"),
    )
    celery_metrics.task_revoked_handler(request=request, terminated=False, signum=None)
    celery_metrics.task_revoked_handler(request=request, terminated=True, signum=9)

    statuses = {
        item["status"] for item in metric_spies["celery_task_total"].labels_seen if "status" in item
    }
    assert {"success", "failure", "revoked", "terminated"} <= statuses
    reasons = {item["reason"] for item in metric_spies["celery_task_retry_total"].labels_seen}
    assert reasons == {"RuntimeError", "backoff", "ValueError"}


def test_queue_metrics_and_prometheus_gauges(
    metric_spies: dict[str, _Metric],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspector = SimpleNamespace(
        active=lambda: {"worker-a": [1, 2]},
        reserved=lambda: {"worker-a": [3], "worker-b": [4, 5]},
        stats=lambda: {},
    )
    monkeypatch.setattr(
        "core.celery.app.control.inspect",
        lambda: inspector,
    )
    assert celery_metrics.get_task_queue_metrics() == {
        "active_tasks": 2,
        "reserved_tasks": 3,
        "workers": 1,
    }
    celery_metrics.update_queue_metrics()
    assert ("set", 1) in metric_spies["celery_active_workers"].values
    assert ("set", 3) in metric_spies["celery_queue_length"].values

    monkeypatch.setattr(
        "core.celery.app.control.inspect",
        lambda: (_ for _ in ()).throw(RuntimeError("broker offline")),
    )
    failed = celery_metrics.get_task_queue_metrics()
    assert failed["workers"] == 0
    assert failed["error"] == "broker offline"


def test_tracking_decorator_records_all_terminal_states(
    metric_spies: dict[str, _Metric],
) -> None:
    @celery_metrics.track_celery_task
    def success() -> str:
        return "ok"

    @celery_metrics.track_celery_task
    def retry() -> None:
        raise Retry()

    @celery_metrics.track_celery_task
    def timeout() -> None:
        raise SoftTimeLimitExceeded()

    @celery_metrics.track_celery_task
    def failure() -> None:
        raise RuntimeError("failed")

    assert success() == "ok"
    with pytest.raises(Retry):
        retry()
    with pytest.raises(SoftTimeLimitExceeded):
        timeout()
    with pytest.raises(RuntimeError, match="failed"):
        failure()

    statuses = {
        item["status"] for item in metric_spies["celery_task_total"].labels_seen if "status" in item
    }
    assert {"success", "retry", "timeout", "failure"} <= statuses
