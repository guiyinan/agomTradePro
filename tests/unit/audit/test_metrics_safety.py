"""Safety regressions for audit Prometheus metrics."""

from unittest.mock import Mock

import pytest
from prometheus_client import REGISTRY, Gauge

from apps.audit.infrastructure import metrics


@pytest.mark.parametrize(
    "latency_seconds",
    [-1.0, float("nan"), float("inf"), float("-inf")],
)
def test_invalid_latency_is_not_observed(
    monkeypatch: pytest.MonkeyPatch,
    latency_seconds: float,
) -> None:
    labels = Mock()
    monkeypatch.setattr(metrics.audit_write_latency_seconds, "labels", labels)

    metrics.record_audit_write_latency(
        module="regime",
        source="test",
        latency_seconds=latency_seconds,
    )

    labels.assert_not_called()


def test_valid_latency_is_observed(monkeypatch: pytest.MonkeyPatch) -> None:
    child = Mock()
    labels = Mock(return_value=child)
    monkeypatch.setattr(metrics.audit_write_latency_seconds, "labels", labels)

    metrics.record_audit_write_latency(
        module="regime",
        source="test",
        latency_seconds=0.25,
    )

    labels.assert_called_once_with(module="regime", source="test")
    child.observe.assert_called_once_with(0.25)


def test_counter_name_collision_with_wrong_collector_type_fails_closed() -> None:
    name = "audit_test_wrong_collector_type"
    gauge = Gauge(name, "test gauge")
    try:
        with pytest.raises(ValueError):
            metrics._safe_counter(name, "test counter", [])
    finally:
        REGISTRY.unregister(gauge)


def test_summary_failure_does_not_expose_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> object:
        raise RuntimeError("secret database address")

    monkeypatch.setattr(metrics.audit_write_success_total, "collect", _raise)

    summary = metrics.get_audit_metrics_summary()

    assert summary["error"] == "metrics_unavailable"
    assert "secret" not in str(summary)


def test_export_failure_does_not_expose_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("secret registry detail")

    monkeypatch.setattr(metrics.CollectorRegistry, "register", _raise)

    content = metrics.export_metrics()

    assert content == "# Audit metrics export unavailable\n"
    assert "secret" not in content


def test_export_rejects_non_bytes_prometheus_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics, "generate_latest", lambda _registry: "not-bytes")

    content = metrics.export_metrics()

    assert content == "# Audit metrics export unavailable\n"
