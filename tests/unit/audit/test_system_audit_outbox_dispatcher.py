from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from apps.audit.application.system_audit_outbox_dispatcher import (
    DispatchSystemAuditOutboxCommand,
    DispatchSystemAuditOutboxUseCase,
    SystemAuditOutboxClaimDTO,
    SystemAuditOutboxDispatchConflict,
)
from tests.unit.audit.test_system_audit_event import make_event

NOW = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=UTC)


class UnitOfWork:
    def __init__(self) -> None:
        self.depth = 0

    def __enter__(self) -> None:
        self.depth += 1

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.depth -= 1


class Publisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.events = []
        self.fail = fail

    def publish(self, event: object) -> None:
        if self.fail:
            raise RuntimeError("secret publisher detail must not escape")
        self.events.append(event)


class Repository:
    def __init__(self, claim: SystemAuditOutboxClaimDTO) -> None:
        self.claim = claim
        self.delivered = []
        self.failed = []

    def claim_due(
        self, *, worker_id: str, as_of: datetime, limit: int
    ) -> tuple[SystemAuditOutboxClaimDTO, ...]:
        del as_of
        if limit < 1:
            return ()
        return (
            SystemAuditOutboxClaimDTO(
                outbox_id=self.claim.outbox_id,
                event=self.claim.event,
                worker_id=worker_id,
                claim_token=self.claim.claim_token,
                claimed_at=self.claim.claimed_at,
                attempt_count=self.claim.attempt_count,
            ),
        )

    def mark_delivered(self, **kwargs: object) -> object:
        self.delivered.append(kwargs)
        return object()

    def mark_failed(self, **kwargs: object) -> object:
        self.failed.append(kwargs)
        return object()


def _claim() -> SystemAuditOutboxClaimDTO:
    return SystemAuditOutboxClaimDTO(
        outbox_id=UUID("00000000-0000-0000-0000-000000000001"),
        event=make_event(),
        worker_id="worker-1",
        claim_token="claim-token",
        claimed_at=NOW,
        attempt_count=1,
    )


def test_dispatch_success_returns_stable_counters_and_outcome() -> None:
    repository = Repository(_claim())
    publisher = Publisher()
    result = DispatchSystemAuditOutboxUseCase(repository, publisher, UnitOfWork()).execute(
        DispatchSystemAuditOutboxCommand(worker_id="worker-1", as_of=NOW)
    )
    assert (result.requested, result.claimed, result.delivered, result.failed) == (20, 1, 1, 0)
    assert result.outcome == "success"
    assert len(publisher.events) == 1
    assert len(repository.delivered) == 1


def test_dispatch_publisher_failure_is_bounded_and_marks_failed() -> None:
    repository = Repository(_claim())
    result = DispatchSystemAuditOutboxUseCase(
        repository, Publisher(fail=True), UnitOfWork()
    ).execute(DispatchSystemAuditOutboxCommand(worker_id="worker-1", as_of=NOW))
    assert (result.claimed, result.delivered, result.failed) == (1, 0, 1)
    assert result.outcome == "failed"
    assert repository.failed[0]["error_code"] == "publisher_error"


def test_dispatch_rejects_invalid_command_and_transition_failure() -> None:
    repository = Repository(_claim())
    use_case = DispatchSystemAuditOutboxUseCase(repository, Publisher(), UnitOfWork())
    with pytest.raises(Exception, match="limit"):
        use_case.execute(DispatchSystemAuditOutboxCommand(worker_id="worker-1", as_of=NOW, limit=0))

    def broken_delivered(**kwargs: object) -> object:
        del kwargs
        raise RuntimeError("transition")

    repository.mark_delivered = broken_delivered  # type: ignore[method-assign]
    with pytest.raises(SystemAuditOutboxDispatchConflict, match="transition"):
        use_case.execute(DispatchSystemAuditOutboxCommand(worker_id="worker-1", as_of=NOW))
