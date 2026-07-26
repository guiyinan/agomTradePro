"""Truthfulness and disclosure tests for the shared Prometheus metrics entrypoint."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import prometheus_client

from core import metrics


class _MetricChild:
    def __init__(self, observations: list[float]) -> None:
        self.observations = observations

    def inc(self) -> None:
        return None

    def observe(self, value: float) -> None:
        self.observations.append(value)


class _Metric:
    def __init__(self) -> None:
        self.labels_seen: list[dict[str, str]] = []
        self.observations: list[float] = []

    def labels(self, **labels: str) -> _MetricChild:
        self.labels_seen.append(labels)
        return _MetricChild(self.observations)


def test_record_api_request_rejects_non_finite_latency(monkeypatch) -> None:
    total = _Metric()
    latency = _Metric()
    errors = _Metric()
    monkeypatch.setattr(metrics, "api_request_total", total)
    monkeypatch.setattr(metrics, "api_request_latency_seconds", latency)
    monkeypatch.setattr(metrics, "api_error_total", errors)

    metrics.record_api_request(
        method="get",
        endpoint="/api/example/",
        status_code=200,
        duration_seconds=float("nan"),
        view_name="ExampleView",
    )

    assert total.labels_seen == [
        {
            "method": "GET",
            "endpoint": "/api/example/",
            "status_code": "200",
            "view_name": "ExampleView",
        }
    ]
    assert latency.observations == []
    assert errors.labels_seen == []


def test_record_celery_task_rejects_raw_retry_reason_and_unknown_status(monkeypatch) -> None:
    total = _Metric()
    duration = _Metric()
    retries = _Metric()
    monkeypatch.setattr(metrics, "celery_task_total", total)
    monkeypatch.setattr(metrics, "celery_task_duration_seconds", duration)
    monkeypatch.setattr(metrics, "celery_task_retry_total", retries)

    metrics.record_celery_task(
        task_name="example.task",
        status="retry",
        duration_seconds=-1.0,
        retry_reason="redis://user:secret@internal-host",
    )
    metrics.record_celery_task(task_name="example.task", status="custom-secret-status")

    assert retries.labels_seen == [{"task_name": "example.task", "reason": "other"}]
    assert duration.observations == []
    assert total.labels_seen[1]["status"] == "unknown"


def test_metrics_summary_counts_4xx_requests_in_total(monkeypatch) -> None:
    samples = [
        SimpleNamespace(
            name="api_request_total",
            labels={"status_code": "404"},
            value=2.0,
        ),
        SimpleNamespace(name="api_error_total", labels={}, value=2.0),
    ]
    registry = SimpleNamespace(
        collect=lambda: [SimpleNamespace(samples=samples)],
    )
    monkeypatch.setattr(prometheus_client, "REGISTRY", registry)

    summary = metrics.get_metrics_summary()

    assert summary["api_requests"] == {"total": 2.0, "errors": 2.0}


def test_metrics_summary_failure_is_redacted(monkeypatch, caplog) -> None:
    def fail_collection() -> None:
        raise RuntimeError("postgres://user:secret@internal-host")

    monkeypatch.setattr(
        prometheus_client,
        "REGISTRY",
        SimpleNamespace(collect=fail_collection),
    )

    with caplog.at_level(logging.ERROR, logger="core.metrics"):
        summary = metrics.get_metrics_summary()

    assert summary["error"] == "metrics_summary_unavailable"
    assert "RuntimeError" in caplog.text
    assert "postgres://user:secret@internal-host" not in caplog.text


def test_api_decorator_prefers_resolver_route_for_endpoint_label(monkeypatch) -> None:
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(
        metrics,
        "record_api_request",
        lambda **payload: recorded.append(payload),
    )

    class _View:
        @metrics.track_api_request
        def get(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(status_code=200)

    request = SimpleNamespace(
        method="GET",
        path="/api/example/987654/",
        resolver_match=SimpleNamespace(route="api/example/<int:item_id>/"),
    )

    response = _View().get(request)

    assert response.status_code == 200
    assert recorded[0]["endpoint"] == "api/example/<int:item_id>/"
