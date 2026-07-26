from datetime import datetime

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.alpha.application import monitoring_tasks
from apps.alpha.infrastructure import alerts as alert_module
from apps.alpha.infrastructure.alerts import (
    AlertNotification,
    AlertNotifier,
    AlertSeverity,
    AlphaAlertManager,
)
from shared.infrastructure.metrics import AlphaMetrics, get_alpha_metrics


def _reset_metrics() -> None:
    get_alpha_metrics().registry.reset_metrics()


@override_settings(
    ALPHA_ALERT_RULE_OVERRIDES={
        "provider_unavailable": {"duration_seconds": 0},
    }
)
def test_alerts_evaluate_each_provider_series_and_notify_once_per_incident() -> None:
    _reset_metrics()
    metrics = get_alpha_metrics()
    metrics.registry.set_gauge(
        AlphaMetrics.PROVIDER_SUCCESS_RATE,
        0.95,
        labels={"provider": "healthy"},
    )
    metrics.registry.set_gauge(
        AlphaMetrics.PROVIDER_SUCCESS_RATE,
        0.30,
        labels={"provider": "broken"},
    )
    manager = AlphaAlertManager()

    assert manager.evaluate_with_notification() == []
    notifications = manager.evaluate_with_notification()

    assert len(notifications) == 1
    assert notifications[0].labels == {"provider": "broken"}
    assert notifications[0].current_value == 0.30
    assert manager.evaluate_with_notification() == []

    metrics.registry.set_gauge(
        AlphaMetrics.PROVIDER_SUCCESS_RATE,
        0.90,
        labels={"provider": "broken"},
    )
    assert manager.evaluate_with_notification() == []
    metrics.registry.set_gauge(
        AlphaMetrics.PROVIDER_SUCCESS_RATE,
        0.20,
        labels={"provider": "broken"},
    )
    assert manager.evaluate_with_notification() == []
    assert len(manager.evaluate_with_notification()) == 1


@override_settings(
    ALPHA_ALERT_RULE_OVERRIDES={
        "provider_unavailable": {"duration_seconds": 0},
    }
)
def test_non_finite_metric_clears_pending_incident_state() -> None:
    _reset_metrics()
    metrics = get_alpha_metrics()
    manager = AlphaAlertManager()
    metrics.registry.set_gauge(
        AlphaMetrics.PROVIDER_SUCCESS_RATE,
        0.30,
        labels={"provider": "broken"},
    )
    assert manager.evaluate_with_notification() == []

    metrics.registry.set_gauge(
        AlphaMetrics.PROVIDER_SUCCESS_RATE,
        float("nan"),
        labels={"provider": "broken"},
    )
    assert manager.evaluate_with_notification() == []
    metrics.registry.set_gauge(
        AlphaMetrics.PROVIDER_SUCCESS_RATE,
        0.20,
        labels={"provider": "broken"},
    )
    assert manager.evaluate_with_notification() == []
    assert len(manager.evaluate_with_notification()) == 1


def test_alert_rule_instances_do_not_share_runtime_mutation() -> None:
    first = AlphaAlertManager()
    first.rules[0].duration_seconds = 0

    second = AlphaAlertManager()

    assert second.rules[0].duration_seconds == 60


@override_settings(
    ALPHA_ALERT_RULE_OVERRIDES={
        "provider_unavailable": {
            "threshold": 0.25,
            "duration_seconds": 15,
            "severity": "warning",
        }
    }
)
def test_alert_rule_runtime_override_is_validated_and_applied() -> None:
    rule = AlphaAlertManager().rules[0]

    assert rule.threshold == 0.25
    assert rule.duration_seconds == 15
    assert rule.severity == "warning"


@override_settings(
    ALPHA_ALERT_RULE_OVERRIDES={
        "provider_unavailable": {
            "threshold": float("nan"),
            "duration_seconds": True,
        }
    }
)
def test_invalid_alert_rule_override_falls_back_to_catalog(caplog) -> None:
    rule = AlphaAlertManager().rules[0]

    assert rule.threshold == 0.5
    assert rule.duration_seconds == 60
    assert "provider_unavailable" in caplog.text


def test_alert_handler_failure_redacts_exception_message(caplog) -> None:
    notifier = AlertNotifier()

    def fail_handler(notification: AlertNotification) -> None:
        raise RuntimeError("broker credential secret")

    notifier.register_handler(fail_handler)
    notifier.notify(
        AlertNotification(
            rule_name="test",
            severity=AlertSeverity.WARNING,
            message="stable alert",
            metric_name="metric",
            current_value=1.0,
            threshold=0.5,
            timestamp=timezone.now(),
        )
    )

    assert "RuntimeError" in caplog.text
    assert "broker credential secret" not in caplog.text


def test_alert_notification_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        AlertNotification(
            rule_name="test",
            severity=AlertSeverity.WARNING,
            message="stable alert",
            metric_name="metric",
            current_value=1.0,
            threshold=0.5,
            timestamp=datetime(2026, 7, 26),
        )


def test_alert_summary_preserves_labeled_series_without_aggregation() -> None:
    _reset_metrics()
    metrics = get_alpha_metrics()
    metrics.registry.set_gauge(
        AlphaMetrics.PROVIDER_SUCCESS_RATE,
        0.9,
        labels={"provider": "healthy"},
    )
    metrics.registry.set_gauge(
        AlphaMetrics.PROVIDER_SUCCESS_RATE,
        0.2,
        labels={"provider": "broken"},
    )

    summary = AlphaAlertManager().get_alert_summary()
    metric_rows = summary["metrics"]

    assert isinstance(metric_rows, dict)
    success_rows = metric_rows[AlphaMetrics.PROVIDER_SUCCESS_RATE]
    assert {row["labels"]["provider"] for row in success_rows} == {
        "healthy",
        "broken",
    }


def test_runtime_alert_manager_is_process_stable(monkeypatch) -> None:
    monkeypatch.setattr(alert_module, "_alpha_alert_manager", None)

    first = alert_module.get_alpha_alert_manager()
    second = alert_module.get_alpha_alert_manager()

    assert first is second


def test_monitoring_task_uses_runtime_alert_manager(monkeypatch) -> None:
    class FakeManager:
        @staticmethod
        def evaluate_all() -> list[str]:
            return ["[CRITICAL] provider_unavailable: stable"]

    monkeypatch.setattr(
        monitoring_tasks,
        "get_alpha_runtime_alert_manager",
        lambda: FakeManager(),
    )

    result = monitoring_tasks.evaluate_alerts()

    assert result["status"] == "alert"
    assert result["count"] == 1
    assert result["alerts"] == ["[CRITICAL] provider_unavailable: stable"]
