"""Safety regressions for audit Prometheus metrics."""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import Mock

import pytest
from prometheus_client import REGISTRY, Gauge

from apps.audit.application.system_audit_outbox_observability import (
    SystemAuditOutboxBacklogSnapshot,
)
from apps.audit.infrastructure import metrics

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _backlog_snapshot(**overrides: object) -> SystemAuditOutboxBacklogSnapshot:
    values: dict[str, object] = {
        "as_of": NOW,
        "pending_count": 2,
        "due_pending_count": 1,
        "claimed_count": 3,
        "expired_claimed_count": 1,
        "failed_count": 4,
        "delivered_count": 5,
        "oldest_backlog_at": NOW - timedelta(seconds=90),
        "oldest_claimed_at": NOW - timedelta(seconds=30),
    }
    values.update(overrides)
    return SystemAuditOutboxBacklogSnapshot(**values)


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


def test_outbox_backlog_projection_uses_fixed_owner_and_bounded_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _backlog_snapshot()
    gauge_names = (
        "system_audit_outbox_pending",
        "system_audit_outbox_oldest_age_seconds",
        "system_audit_outbox_due_pending",
        "system_audit_outbox_claimed",
        "system_audit_outbox_expired_claimed",
        "system_audit_outbox_failed",
        "system_audit_outbox_delivered",
    )
    children: dict[str, Mock] = {}
    for name in gauge_names:
        child = Mock()
        children[name] = child
        monkeypatch.setattr(getattr(metrics, name), "labels", Mock(return_value=child))

    metrics.record_system_audit_outbox_backlog(snapshot)

    for name in gauge_names:
        gauge = getattr(metrics, name)
        gauge.labels.assert_called_once_with(owner="audit")
    children["system_audit_outbox_pending"].set.assert_called_once_with(2)
    children["system_audit_outbox_oldest_age_seconds"].set.assert_called_once_with(90.0)
    children["system_audit_outbox_due_pending"].set.assert_called_once_with(1)
    children["system_audit_outbox_claimed"].set.assert_called_once_with(3)
    children["system_audit_outbox_expired_claimed"].set.assert_called_once_with(1)
    children["system_audit_outbox_failed"].set.assert_called_once_with(4)
    children["system_audit_outbox_delivered"].set.assert_called_once_with(5)


def test_empty_outbox_projection_publishes_zero_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Mock()
    monkeypatch.setattr(
        metrics.system_audit_outbox_oldest_age_seconds, "labels", Mock(return_value=child)
    )

    metrics.record_system_audit_outbox_backlog(
        _backlog_snapshot(
            pending_count=0,
            due_pending_count=0,
            claimed_count=0,
            expired_claimed_count=0,
            oldest_backlog_at=None,
            oldest_claimed_at=None,
        )
    )

    child.set.assert_called_once_with(0.0)


def test_invalid_outbox_projection_is_ignored_without_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = Mock()
    monkeypatch.setattr(metrics.system_audit_outbox_pending, "labels", labels)

    metrics.record_system_audit_outbox_backlog(cast(SystemAuditOutboxBacklogSnapshot, object()))

    labels.assert_not_called()


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
