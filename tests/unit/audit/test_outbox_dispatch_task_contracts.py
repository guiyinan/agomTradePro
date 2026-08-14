"""Contract tests for the fail-closed audit outbox dispatch task."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from apps.audit.application import tasks
from apps.audit.application.system_audit_outbox_dispatcher import (
    SystemAuditOutboxDispatchUnavailable,
)
from apps.audit.infrastructure.system_audit_outbox_runtime import (
    SystemAuditOutboxPublisherUnavailable,
    get_system_audit_outbox_dispatcher,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def test_dispatch_task_rejects_invalid_limit_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid task input cannot reach repository or publisher composition."""

    def unexpected_composition() -> object:
        raise AssertionError("composition must not run for invalid input")

    monkeypatch.setattr(tasks, "get_system_audit_outbox_dispatcher", unexpected_composition)

    result = tasks.dispatch_system_audit_outbox_task.run(
        limit=0,
        worker_id="audit-worker",
        as_of=NOW.isoformat(),
    )

    assert result == {
        "outcome": "failed",
        "success": False,
        "reason_code": "limit_must_be_between_1_and_100",
        "requested": 0,
        "claimed": 0,
        "delivered": 0,
        "failed": 1,
    }


def test_dispatch_task_returns_blocked_before_any_claim_when_sink_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable canonical sink never turns an outbox row into delivered."""

    def blocked_composition() -> object:
        raise SystemAuditOutboxDispatchUnavailable(
            "publisher is not wired",
            reason_code="publisher_not_wired",
        )

    monkeypatch.setattr(tasks, "get_system_audit_outbox_dispatcher", blocked_composition)

    result = tasks.dispatch_system_audit_outbox_task.run(
        limit=20,
        worker_id="audit-worker",
        as_of=NOW.isoformat(),
    )

    assert result["outcome"] == "blocked"
    assert result["success"] is False
    assert result["reason_code"] == "publisher_not_wired"
    assert result["requested"] == 20
    assert result["claimed"] == 0
    assert result["delivered"] == 0
    assert result["failed"] == 0


def test_dispatch_task_redacts_unexpected_composition_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected composition errors produce a stable failure without secrets."""

    def failed_composition() -> object:
        raise RuntimeError("postgres://audit:secret@example.test/audit")

    monkeypatch.setattr(tasks, "get_system_audit_outbox_dispatcher", failed_composition)

    result = tasks.dispatch_system_audit_outbox_task.run(
        limit=3,
        worker_id="audit-worker",
        as_of=NOW.isoformat(),
    )

    assert result["outcome"] == "failed"
    assert result["reason_code"] == "dispatch_composition_failed"
    assert result["claimed"] == 0
    assert result["delivered"] == 0
    assert "postgres://" not in caplog.text
    assert "secret" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_runtime_composition_is_explicitly_blocked_until_canonical_sink_exists() -> None:
    """The infrastructure gate does not import or fall back to the generic event bus."""

    with pytest.raises(SystemAuditOutboxPublisherUnavailable) as exc_info:
        get_system_audit_outbox_dispatcher()

    assert exc_info.value.reason_code == "publisher_not_wired"
