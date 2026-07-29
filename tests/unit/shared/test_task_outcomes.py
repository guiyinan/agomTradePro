"""Tests for framework-neutral background-task business outcomes."""

import pytest

from shared.domain.task_outcomes import (
    TaskBusinessOutcome,
    resolve_task_business_outcome,
    task_business_failure_message,
)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"success": True, "outcome": "success"}, TaskBusinessOutcome.SUCCESS),
        (
            {"success": True, "outcome": "partial", "partial_success": True},
            TaskBusinessOutcome.PARTIAL,
        ),
        ({"success": True, "outcome": "noop"}, TaskBusinessOutcome.NOOP),
        (
            {"success": True, "stage": "gate_blocked"},
            TaskBusinessOutcome.BLOCKED,
        ),
        ({"success": False, "outcome": "success"}, TaskBusinessOutcome.FAILED),
        ({"success": False, "error": "provider down"}, TaskBusinessOutcome.FAILED),
        ({"outcome": "not-real"}, TaskBusinessOutcome.UNKNOWN),
        ("not-a-payload", TaskBusinessOutcome.UNKNOWN),
    ],
)
def test_resolve_task_business_outcome(
    payload: object,
    expected: TaskBusinessOutcome,
) -> None:
    """Normalize explicit, legacy, conflicting, and malformed payloads safely."""

    assert resolve_task_business_outcome(payload) is expected


def test_task_business_failure_message_includes_stage() -> None:
    """Keep the failure reason useful when Celery itself completed normally."""

    payload = {"success": False, "stage": "sync", "error": "all providers failed"}

    assert task_business_failure_message(payload) == "[sync] all providers failed"


def test_task_business_failure_message_ignores_non_failure() -> None:
    """Do not synthesize errors for successful or partial task outcomes."""

    assert task_business_failure_message({"success": True, "outcome": "partial"}) is None
