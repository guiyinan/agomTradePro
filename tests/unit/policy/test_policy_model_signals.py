from datetime import date
from unittest.mock import patch

import pytest

from apps.policy.infrastructure.models import PolicyLog


def _approved_event() -> PolicyLog:
    return PolicyLog._default_manager.create(
        event_date=date(2026, 7, 25),
        level="P1",
        title="Policy signal transition",
        description="A sufficiently detailed policy event for signal tests.",
        evidence_url="https://example.com/policy/signal",
        audit_status="manual_approved",
    )


@pytest.mark.django_db
def test_non_level_update_does_not_schedule_signal_reevaluation(
    django_capture_on_commit_callbacks,
) -> None:
    event = _approved_event()

    with (
        patch("apps.policy.application.tasks.trigger_signal_reevaluation.delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        event.description = "Only the narrative changed; the policy level did not."
        event.save(update_fields=["description"])

    delay.assert_not_called()


@pytest.mark.django_db
def test_level_transition_schedules_signal_reevaluation_after_commit(
    django_capture_on_commit_callbacks,
) -> None:
    event = _approved_event()

    with (
        patch("apps.policy.application.tasks.trigger_signal_reevaluation.delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        event.level = "P2"
        event.save(update_fields=["level"])
        delay.assert_not_called()

    delay.assert_called_once_with(
        new_level=2,
        event_date="2026-07-25",
    )


@pytest.mark.django_db
def test_pending_classification_does_not_schedule_invalid_numeric_level(
    django_capture_on_commit_callbacks,
) -> None:
    event = _approved_event()

    with (
        patch("apps.policy.application.tasks.trigger_signal_reevaluation.delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        event.level = "PX"
        event.save(update_fields=["level"])

    delay.assert_not_called()
