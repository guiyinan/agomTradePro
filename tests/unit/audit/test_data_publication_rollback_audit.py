"""Contracts for canonical publication rollback audit events."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.audit.application.data_publication_rollback_audit import (
    AppendDataPublicationRollbackAuditObservationUseCase,
    DataPublicationRollbackAuditObservation,
    build_data_publication_rollback_audit_event,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
SCOPE = AuditScopeRef("tenant:research", "owner:alice")
TARGET_ID = "00000000-0000-4000-8000-000000000001"
ROLLBACK_ID = "00000000-0000-4000-8000-000000000002"
PREVIOUS_ID = "00000000-0000-4000-8000-000000000003"
RUN_ID = "00000000-0000-4000-8000-000000000004"


def _observation(
    *,
    publication_hash: str = "a" * 64,
    rollback_content_hash: str = "b" * 64,
    previous_publication_hash: str = "c" * 64,
    scope: AuditScopeRef | None = None,
) -> DataPublicationRollbackAuditObservation:
    """Build one exact publication rollback observation."""

    return DataPublicationRollbackAuditObservation(
        dataset_key="equity.price.bar",
        publication_key="current",
        publication_id=TARGET_ID,
        publication_version="price.v7",
        publication_hash=publication_hash,
        rollback_id=ROLLBACK_ID,
        rollback_version="1",
        rollback_content_hash=rollback_content_hash,
        previous_publication_id=PREVIOUS_ID,
        previous_publication_version="price.v8",
        previous_publication_hash=previous_publication_hash,
        run_id=RUN_ID,
        occurred_at=NOW,
        recorded_at=NOW,
        outcome=AuditOutcome.ROLLED_BACK,
        scope=scope,
    )


def test_rollback_builder_is_required_warning_and_exactly_correlated() -> None:
    event = build_data_publication_rollback_audit_event(
        _observation(scope=SCOPE), sequence_no=1, predecessor_hash=None
    )

    assert event.event_type == "data.publication.rolled_back"
    assert event.category.value == "data.reliability"
    assert event.outcome is AuditOutcome.ROLLED_BACK
    assert event.write_policy.value == "required"
    assert event.severity.value == "warning"
    assert event.reason_codes == ("publication_rolled_back",)
    assert event.correlations.dataset_key == "equity.price.bar"
    assert event.correlations.publication_id == TARGET_ID
    assert event.correlations.evidence_ref == ROLLBACK_ID
    assert event.correlations.run_id == RUN_ID
    assert [reference.artifact_type for reference in event.evidence_refs] == [
        "canonical_publication",
        "publication_rollback",
        "canonical_publication",
    ]
    assert [reference.artifact_id for reference in event.evidence_refs] == [
        TARGET_ID,
        ROLLBACK_ID,
        PREVIOUS_ID,
    ]
    assert [reference.content_hash for reference in event.evidence_refs] == [
        "a" * 64,
        "b" * 64,
        "c" * 64,
    ]
    assert event.resource is not None
    assert event.resource.resource_id == TARGET_ID
    assert event.detail["publication_key"] == "current"
    assert event.detail["rollback_id"] == ROLLBACK_ID
    assert event.detail["previous_publication_id"] == PREVIOUS_ID
    assert "reason" not in event.detail
    assert "operator" not in event.detail
    assert event.scope == SCOPE


@pytest.mark.parametrize(
    "changes",
    [
        {"publication_id": "not-a-uuid"},
        {"publication_hash": "A" * 64},
        {"rollback_id": "not-a-uuid"},
        {"rollback_content_hash": "b" * 63},
        {"previous_publication_id": TARGET_ID},
        {"occurred_at": datetime(2026, 8, 27, 12, 0)},
        {"recorded_at": datetime(2026, 8, 27, 12, 0)},
        {"outcome": AuditOutcome.SUCCESS},
    ],
)
def test_invalid_rollback_observation_fails_closed(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "dataset_key": "equity.price.bar",
        "publication_key": "current",
        "publication_id": TARGET_ID,
        "publication_version": "price.v7",
        "publication_hash": "a" * 64,
        "rollback_id": ROLLBACK_ID,
        "rollback_version": "1",
        "rollback_content_hash": "b" * 64,
        "previous_publication_id": PREVIOUS_ID,
        "previous_publication_version": "price.v8",
        "previous_publication_hash": "c" * 64,
        "run_id": RUN_ID,
        "occurred_at": NOW,
        "recorded_at": NOW,
        "outcome": AuditOutcome.ROLLED_BACK,
        "scope": None,
    }
    values.update(changes)

    with pytest.raises((TypeError, ValueError)):
        DataPublicationRollbackAuditObservation(**values)


class _ScopeProvider:
    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        assert as_of == NOW
        return SCOPE


class _Atomic(AbstractContextManager[None]):
    def __init__(self, writer: _Writer) -> None:
        self._writer = writer

    def __enter__(self) -> None:
        self._writer.active = True
        return None

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
        self._writer.active = False
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
        assert stream_id == "data.publication:equity.price.bar"
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


def test_append_binds_scope_and_replays_exact_first_winner() -> None:
    writer = _Writer()
    use_case = AppendDataPublicationRollbackAuditObservationUseCase(writer, _ScopeProvider())

    first = use_case.execute(_observation())
    replay = use_case.execute(_observation())

    assert replay.event == first.event
    assert first.event.scope == SCOPE
    assert first.event.sequence_no == 1
    assert first.event.predecessor_hash is None
    assert len(writer.events) == 1
