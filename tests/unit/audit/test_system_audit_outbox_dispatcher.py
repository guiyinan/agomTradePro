from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from apps.audit.application.system_audit_composition import (
    CanonicalSystemAuditPublishReceipt,
)
from apps.audit.application.system_audit_outbox_dispatcher import (
    DispatchSystemAuditOutboxCommand,
    DispatchSystemAuditOutboxUseCase,
    SystemAuditOutboxClaimDTO,
    SystemAuditOutboxDispatchConflict,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
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
    def __init__(self, *, fail: bool = False, fail_event_ids: set[str] | None = None) -> None:
        self.events = []
        self.fail = fail
        self.fail_event_ids = fail_event_ids or set()

    def publish(self, event: object) -> CanonicalSystemAuditPublishReceipt:
        if self.fail or getattr(event, "event_id", None) in self.fail_event_ids:
            raise RuntimeError("secret publisher detail must not escape")
        self.events.append(event)
        return CanonicalSystemAuditPublishReceipt.from_event(event)


class Repository:
    def __init__(
        self, claim: SystemAuditOutboxClaimDTO | tuple[SystemAuditOutboxClaimDTO, ...]
    ) -> None:
        self.claims = (claim,) if isinstance(claim, SystemAuditOutboxClaimDTO) else claim
        self.delivered = []
        self.failed = []

    def claim_due(
        self, *, worker_id: str, as_of: datetime, limit: int
    ) -> tuple[SystemAuditOutboxClaimDTO, ...]:
        del as_of
        if limit < 1:
            return ()
        return tuple(
            SystemAuditOutboxClaimDTO(
                outbox_id=claim.outbox_id,
                event=claim.event,
                worker_id=worker_id,
                claim_token=claim.claim_token,
                claimed_at=claim.claimed_at,
                attempt_count=claim.attempt_count,
            )
            for claim in self.claims[:limit]
        )

    def mark_delivered(self, **kwargs: object) -> object:
        self.delivered.append(kwargs)
        return object()

    def mark_failed(self, **kwargs: object) -> object:
        self.failed.append(kwargs)
        return object()


def _claim(
    *,
    outbox_id: UUID = UUID("00000000-0000-0000-0000-000000000001"),
    event: SystemAuditEvent | None = None,
) -> SystemAuditOutboxClaimDTO:
    return SystemAuditOutboxClaimDTO(
        outbox_id=outbox_id,
        event=make_event() if event is None else event,
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


def test_dispatch_rejects_publisher_without_exact_preservation_receipt() -> None:
    """Generic/memory-style publishers cannot turn a claim into delivered."""

    class NonCanonicalPublisher:
        def publish(self, event: object) -> None:
            del event
            return None

    repository = Repository(_claim())
    result = DispatchSystemAuditOutboxUseCase(
        repository,
        NonCanonicalPublisher(),
        UnitOfWork(),
    ).execute(DispatchSystemAuditOutboxCommand(worker_id="worker-1", as_of=NOW))

    assert (result.claimed, result.delivered, result.failed) == (1, 0, 1)
    assert result.outcome == "failed"
    assert repository.failed[0]["error_code"] == "publisher_contract_violation"


def test_dispatch_classifies_noncanonical_receipt_payload_as_contract_failure() -> None:
    class MalformedPayloadPublisher:
        def publish(self, event: SystemAuditEvent) -> CanonicalSystemAuditPublishReceipt:
            receipt = CanonicalSystemAuditPublishReceipt.from_event(event)
            return replace(receipt, canonical_payload={"invalid": object()})

    repository = Repository(_claim())
    result = DispatchSystemAuditOutboxUseCase(
        repository,
        MalformedPayloadPublisher(),
        UnitOfWork(),
    ).execute(DispatchSystemAuditOutboxCommand(worker_id="worker-1", as_of=NOW))

    assert (result.claimed, result.delivered, result.failed) == (1, 0, 1)
    assert repository.failed[0]["error_code"] == "publisher_contract_violation"


def test_dispatch_mixed_batch_reports_partial_and_keeps_each_transition() -> None:
    first = _claim()
    second = _claim(
        outbox_id=UUID("00000000-0000-0000-0000-000000000002"),
        event=make_event(event_id="evt-2", idempotency_key="fetch:run-2"),
    )
    repository = Repository((first, second))
    result = DispatchSystemAuditOutboxUseCase(
        repository,
        Publisher(fail_event_ids={"evt-2"}),
        UnitOfWork(),
    ).execute(DispatchSystemAuditOutboxCommand(worker_id="worker-1", as_of=NOW, limit=2))

    assert (result.requested, result.claimed, result.delivered, result.failed) == (2, 2, 1, 1)
    assert result.outcome == "partial"
    assert [item["outbox_id"] for item in repository.delivered] == [first.outbox_id]
    assert [item["outbox_id"] for item in repository.failed] == [second.outbox_id]


def test_dispatch_empty_batch_is_noop() -> None:
    repository = Repository(())
    result = DispatchSystemAuditOutboxUseCase(repository, Publisher(), UnitOfWork()).execute(
        DispatchSystemAuditOutboxCommand(worker_id="worker-1", as_of=NOW)
    )
    assert (result.claimed, result.delivered, result.failed) == (0, 0, 0)
    assert result.outcome == "noop"


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
