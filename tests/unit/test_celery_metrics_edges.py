"""Safety and contract tests for global Celery metrics handlers."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from core import celery_metrics


def test_task_prerun_ignores_missing_task_id() -> None:
    celery_metrics._task_start_times.clear()

    celery_metrics.task_prerun_handler(task_id=None)

    assert celery_metrics._task_start_times == {}


def test_queue_metrics_counts_reserved_only_worker(monkeypatch) -> None:
    from core.celery import app

    inspect = SimpleNamespace(
        active=lambda: {},
        reserved=lambda: {"worker-a": [{"id": "one"}]},
        stats=lambda: {},
    )
    monkeypatch.setattr(app.control, "inspect", lambda: inspect)

    metrics = celery_metrics.get_task_queue_metrics()

    assert metrics == {
        "active_tasks": 0,
        "reserved_tasks": 1,
        "workers": 1,
    }


def test_queue_metrics_redacts_inspection_failure(monkeypatch, caplog) -> None:
    from core.celery import app

    def fail_inspection() -> None:
        raise RuntimeError("redis://user:secret@internal-host")

    monkeypatch.setattr(app.control, "inspect", fail_inspection)

    with caplog.at_level(logging.ERROR, logger="core.celery_metrics"):
        metrics = celery_metrics.get_task_queue_metrics()

    assert metrics == {
        "active_tasks": 0,
        "reserved_tasks": 0,
        "workers": 0,
        "error": "queue_metrics_unavailable",
    }
    assert "RuntimeError" in caplog.text
    assert "redis://user:secret@internal-host" not in caplog.text


def test_postrun_metrics_use_bounded_dynamic_task_name(monkeypatch) -> None:
    from core import metrics as metrics_module

    observed_labels: list[dict[str, str]] = []

    class _MetricChild:
        def inc(self) -> None:
            return None

        def observe(self, value: float) -> None:
            return None

    class _Metric:
        def labels(self, **labels: str) -> _MetricChild:
            observed_labels.append(labels)
            return _MetricChild()

    monkeypatch.setattr(metrics_module, "celery_task_total", _Metric())
    monkeypatch.setattr(metrics_module, "celery_task_duration_seconds", _Metric())
    long_name = "x" * 250

    celery_metrics.task_postrun_handler(
        task_id=None,
        task=SimpleNamespace(name=long_name),
        retval=None,
    )

    assert observed_labels == [{"task_name": "x" * 200, "status": "success"}]


def test_retry_metrics_do_not_publish_raw_reason(monkeypatch, caplog) -> None:
    from core import metrics as metrics_module

    observed_labels: list[dict[str, str]] = []

    class _MetricChild:
        def inc(self) -> None:
            return None

    class _Metric:
        def labels(self, **labels: str) -> _MetricChild:
            observed_labels.append(labels)
            return _MetricChild()

    monkeypatch.setattr(metrics_module, "celery_task_retry_total", _Metric())

    with caplog.at_level(logging.DEBUG, logger="core.celery_metrics"):
        celery_metrics.task_retry_handler(
            request=SimpleNamespace(task="example.task", id="task-1"),
            reason="redis://user:secret@internal-host",
        )

    assert observed_labels == [{"task_name": "example.task", "reason": "str"}]
    assert "redis://user:secret@internal-host" not in caplog.text


def test_track_celery_task_preserves_result_and_records_success(monkeypatch) -> None:
    from core import metrics as metrics_module

    statuses: list[str] = []
    durations: list[float] = []

    class _CounterChild:
        def inc(self) -> None:
            return None

    class _Counter:
        def labels(self, *, task_name: str, status: str) -> _CounterChild:
            statuses.append(status)
            return _CounterChild()

    class _HistogramChild:
        def observe(self, value: float) -> None:
            durations.append(value)

    class _Histogram:
        def labels(self, *, task_name: str) -> _HistogramChild:
            return _HistogramChild()

    monkeypatch.setattr(metrics_module, "celery_task_total", _Counter())
    monkeypatch.setattr(metrics_module, "celery_task_duration_seconds", _Histogram())

    @celery_metrics.track_celery_task
    def add(left: int, right: int) -> int:
        return left + right

    assert add(2, 3) == 5
    assert statuses == ["success"]
    assert len(durations) == 1
    assert durations[0] >= 0.0
