"""Contract tests for the fail-closed audit outbox dispatch task."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from apps.audit.application import tasks
from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
from apps.audit.application.system_audit_outbox_dispatcher import (
    DispatchSystemAuditOutboxResult,
    DispatchSystemAuditOutboxUseCase,
    SystemAuditOutboxDispatchUnavailable,
)
from apps.audit.infrastructure import system_audit_outbox_runtime as runtime_composition_root
from apps.audit.infrastructure.system_audit_outbox_runtime import (
    SystemAuditOutboxPublisherUnavailable,
    get_system_audit_outbox_dispatcher,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("delivered", "failed", "outcome", "reason"),
    (
        (0, 0, "noop", "no_due_rows"),
        (2, 0, "success", "dispatch_completed"),
        (1, 1, "partial", "dispatch_partially_failed"),
        (0, 2, "failed", "dispatch_failed"),
    ),
)
def test_dispatch_task_reports_finalized_batch(
    monkeypatch: pytest.MonkeyPatch, delivered: int, failed: int, outcome: str, reason: str
) -> None:
    """Expose confirmed deliveries and failures for a bounded recovery batch."""
    dispatcher = Mock(spec=DispatchSystemAuditOutboxUseCase)
    dispatcher.execute.return_value = DispatchSystemAuditOutboxResult(
        requested=3, claimed=delivered + failed, delivered=delivered, failed=failed
    )
    monkeypatch.setattr(tasks, "get_system_audit_outbox_dispatcher", lambda: dispatcher)

    result = tasks.dispatch_system_audit_outbox_task.run(limit=3, worker_id="audit-worker")

    assert result["outcome"] == outcome
    assert result["reason_code"] == reason
    assert result["success"] == (failed == 0)
    assert result["requested"] == 3
    assert result["claimed"] == delivered + failed
    assert result["delivered"] == result["succeeded"] == result["stored"] == delivered
    assert result["failed"] == failed


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
        "succeeded": 0,
        "stored": 0,
        "counts_unavailable": False,
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


@pytest.mark.parametrize("reason_code", ["authority_not_wired", "authority_unavailable"])
def test_dispatch_task_returns_blocked_for_authority_preflight_failure(
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
) -> None:
    """Authority failure is blocked with zero claim/delivery/failure counters."""

    class AuthorityBlockedDispatcher:
        def execute(self, command: object) -> object:
            del command
            raise SystemAuditOutboxDispatchUnavailable(
                "authority is unavailable",
                reason_code=reason_code,
            )

    monkeypatch.setattr(
        tasks,
        "get_system_audit_outbox_dispatcher",
        lambda: AuthorityBlockedDispatcher(),
    )

    result = tasks.dispatch_system_audit_outbox_task.run(
        limit=20,
        worker_id="audit-worker",
        as_of=NOW.isoformat(),
    )

    assert result == {
        "outcome": "blocked",
        "success": False,
        "reason_code": reason_code,
        "requested": 20,
        "claimed": 0,
        "delivered": 0,
        "succeeded": 0,
        "stored": 0,
        "failed": 0,
    }


@pytest.mark.parametrize(
    ("error", "reason"),
    (
        (RuntimeError("completion unknown"), "dispatch_execution_failed"),
        (SystemAuditOutboxDispatchUnavailable("claim result unknown"), "dispatch_unavailable"),
    ),
)
def test_dispatch_execution_interruption_requires_receipt_reconciliation(
    monkeypatch: pytest.MonkeyPatch, error: Exception, reason: str
) -> None:
    """A missing batch result cannot certify zero writes across committed transactions."""
    dispatcher = Mock(spec=DispatchSystemAuditOutboxUseCase)
    dispatcher.execute.side_effect = error
    monkeypatch.setattr(tasks, "get_system_audit_outbox_dispatcher", lambda: dispatcher)

    result = tasks.dispatch_system_audit_outbox_task.run(limit=2, worker_id="audit-worker")

    assert result["outcome"] == "failed"
    assert result["reason_code"] == reason
    assert result["counts_unavailable"] is True
    assert result["claimed"] is result["delivered"] is None
    assert result["succeeded"] is result["stored"] is result["failed"] is None


def test_dispatch_task_redacts_unexpected_composition_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected composition errors produce a stable failure without secrets."""

    def failed_composition() -> object:
        raise RuntimeError("postgres://audit:secret@example.test/audit")

    monkeypatch.setattr(tasks, "get_system_audit_outbox_dispatcher", failed_composition)
    monkeypatch.setattr(tasks.logger, "handlers", [*tasks.logger.handlers, caplog.handler])

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


def test_runtime_composition_maps_missing_snapshot_to_blocked_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The infrastructure entry point preserves a safe configuration reason."""

    def missing_snapshot(**kwargs: object) -> object:
        del kwargs
        raise SystemAuditCompositionUnavailable(
            "system audit runtime configuration is unavailable",
            reason_code="snapshot_unavailable",
        )

    monkeypatch.setattr(
        runtime_composition_root,
        "build_system_audit_outbox_dispatcher",
        missing_snapshot,
    )

    with pytest.raises(SystemAuditOutboxPublisherUnavailable) as exc_info:
        get_system_audit_outbox_dispatcher()

    assert exc_info.value.reason_code == "snapshot_unavailable"
