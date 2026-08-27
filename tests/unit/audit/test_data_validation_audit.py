"""Contract tests for canonical Data Center validation-rejection events."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from apps.audit.application.data_validation_audit import (
    AppendDataValidationRejectedObservationUseCase,
    DataValidationRejectedObservation,
    build_data_validation_rejected_event,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
RAW_HASH = "a" * 64
SCOPE = AuditScopeRef("tenant:research", "owner:alice")


def _observation(
    *,
    dataset_key: str = "equity.price.bar",
    rejected_count: int = 2,
    raw_audit_content_hash: str = RAW_HASH,
    rejection_reason: str = "schema_mismatch",
    error_class: str | None = "ValidationError",
    scope: AuditScopeRef | None = None,
) -> DataValidationRejectedObservation:
    """Build one valid validation rejection observation."""

    return DataValidationRejectedObservation(
        dataset_key=dataset_key,
        validator_key="price.schema.v1",
        provider_key="provider-main",
        run_id="run-1",
        ingested_run_id="ingested-1",
        raw_audit_id="raw-1",
        raw_audit_version="1",
        raw_audit_content_hash=raw_audit_content_hash,
        rejection_reason=rejection_reason,
        error_class=error_class,
        rejected_count=rejected_count,
        occurred_at=NOW,
        recorded_at=NOW,
        scope=scope,
    )


def test_builds_blocked_validation_event_with_exact_correlations_and_evidence() -> None:
    event = build_data_validation_rejected_event(
        _observation(), sequence_no=1, predecessor_hash=None
    )

    assert event.event_type == "data.validation.rejected"
    assert event.category.value == "data.reliability"
    assert event.outcome is AuditOutcome.BLOCKED
    assert event.write_policy.value == "transactional_outbox"
    assert event.severity.value == "error"
    assert event.reason_codes == ("validation_rejected", "schema_mismatch")
    assert event.stream_id == "data.validation:equity.price.bar"
    assert event.idempotency_key.startswith("data-validation:run-1:ingested-1:")
    assert event.correlations.run_id == "run-1"
    assert event.correlations.ingested_run_id == "ingested-1"
    assert event.resource is not None
    assert event.resource.resource_id == "raw-1"
    assert event.evidence_refs[0].content_hash == RAW_HASH


def test_error_class_is_retained_without_exception_message_or_sensitive_detail() -> None:
    event = build_data_validation_rejected_event(
        _observation(error_class="ValueError"),
        sequence_no=1,
        predecessor_hash=None,
    )

    assert event.detail["error_class"] == "ValueError"
    assert "exception_message" not in event.detail
    assert "message" not in event.detail


@pytest.mark.parametrize(
    "changes",
    [
        {"dataset_key": ""},
        {"rejection_reason": ""},
        {"rejected_count": 0},
        {"rejected_count": -1},
        {"raw_audit_content_hash": "A" * 64},
        {"raw_audit_content_hash": "not-a-hash"},
        {"error_class": "ValueError: secret-token=redacted"},
    ],
)
def test_invalid_validation_observations_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _observation(**changes)


class _ScopeProvider:
    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        assert as_of == NOW
        return SCOPE


class _Atomic(AbstractContextManager[None]):
    def __init__(self, writer: _Writer) -> None:
        self.writer = writer

    def __enter__(self) -> None:
        self.writer.active = True
        return None

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
        self.writer.active = False
        return False


class _Writer:
    database_alias = "default"

    def __init__(self) -> None:
        self.active = False
        self.events: list[SystemAuditEvent] = []

    def atomic(self) -> AbstractContextManager[None]:
        return _Atomic(self)

    def get_winner(
        self, *, event_id: str, event_version: str, as_of: datetime
    ) -> SystemAuditEvent | None:
        del event_version, as_of
        return next((event for event in self.events if event.event_id == event_id), None)

    def get_current_head(
        self, *, stream_id: str, as_of: datetime, scope: AuditScopeRef
    ) -> SystemAuditEvent | None:
        assert stream_id == "data.validation:equity.price.bar"
        assert as_of == NOW
        assert scope == SCOPE
        return self.events[-1] if self.events else None

    def append_and_enqueue(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        assert self.active
        assert expected_predecessor_hash == event.predecessor_hash
        assert recorded_at == NOW
        existing = next((item for item in self.events if item.event_id == event.event_id), None)
        winner = existing or event
        if existing is None:
            self.events.append(event)
        return SystemAuditEventOutboxCommit(
            event=winner,
            outbox_id=uuid4(),
            event_id=winner.event_id,
            idempotency_key=winner.idempotency_key,
        )


def test_append_binds_authoritative_scope_and_replays_exact_winner() -> None:
    writer = _Writer()
    use_case = AppendDataValidationRejectedObservationUseCase(writer, _ScopeProvider())
    observation = _observation()

    first = use_case.execute(observation)
    replay = use_case.execute(observation)

    assert first.event.scope == SCOPE
    assert replay.event == first.event
    assert len(writer.events) == 1
    assert isinstance(first.outbox_id, UUID)
