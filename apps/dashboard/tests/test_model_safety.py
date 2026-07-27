"""Safety contracts for Dashboard infrastructure models."""

import pytest

from apps.dashboard.infrastructure.models import DashboardAlertModel


@pytest.mark.django_db
def test_alert_trigger_increment_is_atomic_across_stale_instances() -> None:
    """Two workers holding stale models must preserve both trigger events."""

    alert = DashboardAlertModel._default_manager.create(
        alert_id="atomic-alert",
        name="Atomic alert",
    )
    first_worker = DashboardAlertModel._default_manager.get(pk=alert.pk)
    second_worker = DashboardAlertModel._default_manager.get(pk=alert.pk)

    first_worker.update_trigger()
    second_worker.update_trigger()

    alert.refresh_from_db()
    assert alert.trigger_count == 2
    assert first_worker.trigger_count == 1
    assert second_worker.trigger_count == 2
    assert alert.last_triggered_at is not None


def test_alert_trigger_rejects_unsaved_instance() -> None:
    """An unsaved alert has no stable row to update atomically."""

    alert = DashboardAlertModel(alert_id="unsaved-alert", name="Unsaved")

    with pytest.raises(ValueError, match="persisted"):
        alert.update_trigger()
