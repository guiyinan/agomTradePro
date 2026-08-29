"""Contracts for reconciliation-backed conflict lifecycle events."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.audit.application.data_conflict_audit import (
    AppendDataConflictAuditObservationUseCase,
    DataConflictAuditObservation,
    build_data_conflict_audit_event,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
SCOPE = AuditScopeRef("tenant:research", "owner:alice")
EVIDENCE_ID = "00000000-0000-4000-8000-000000000001"
PREVIOUS_EVIDENCE_ID = "00000000-0000-4000-8000-000000000002"


def _observation(
    *,
    evidence_id: str = EVIDENCE_ID,
    transition: str = "detected",
    conflict_count: int = 1,
    previous_conflict_count: int | None = None,
    previous_evidence_id: str | None = None,
    previous_evidence_version: str | None = None,
    previous_evidence_content_hash: str | None = None,
    evidence_content_hash: str = "a" * 64,
) -> DataConflictAuditObservation:
    """Build one exact reconciliation conflict transition."""

    return DataConflictAuditObservation(
        dataset_key="equity.price.bar",
        transition=transition,
        evidence_id=evidence_id,
        evidence_version="1",
        evidence_content_hash=evidence_content_hash,
        conflict_count=conflict_count,
        previous_conflict_count=previous_conflict_count,
        previous_evidence_id=previous_evidence_id,
        previous_evidence_version=previous_evidence_version,
        previous_evidence_content_hash=previous_evidence_content_hash,
        occurred_at=NOW,
        recorded_at=NOW,
    )


def test_first_semantic_conflict_builds_detected_event_with_exact_evidence() -> None:
    event = build_data_conflict_audit_event(
        _observation(),
        sequence_no=1,
        predecessor_hash=None,
    )

    assert event.event_type == "data.conflict.detected"
    assert event.category.value == "data.reliability"
    assert event.outcome is AuditOutcome.DETECTED
    assert event.write_policy.value == "transactional_outbox"
    assert event.severity.value == "error"
    assert event.correlations.dataset_key == "equity.price.bar"
    assert event.evidence_refs[0].artifact_type == "reconciliation_evidence"
    assert event.evidence_refs[0].artifact_id == EVIDENCE_ID
    assert event.evidence_refs[0].artifact_version == "1"
    assert event.evidence_refs[0].content_hash == "a" * 64
    assert event.detail["previous_conflict_count"] is None
    assert event.detail["conflict_count"] == 1
    assert event.reason_codes == ("conflict_detected",)


def test_conflict_to_clean_builds_required_resolved_event_with_both_snapshots() -> None:
    event = build_data_conflict_audit_event(
        _observation(
            transition="resolved",
            conflict_count=0,
            previous_conflict_count=2,
            previous_evidence_id=PREVIOUS_EVIDENCE_ID,
            previous_evidence_version="1",
            previous_evidence_content_hash="b" * 64,
        ),
        sequence_no=2,
        predecessor_hash="c" * 64,
    )

    assert event.event_type == "data.conflict.resolved"
    assert event.outcome is AuditOutcome.RECOVERED
    assert event.write_policy.value == "required"
    assert event.severity.value == "info"
    assert event.predecessor_hash == "c" * 64
    assert [reference.artifact_id for reference in event.evidence_refs] == [
        EVIDENCE_ID,
        PREVIOUS_EVIDENCE_ID,
    ]
    assert event.detail["previous_conflict_count"] == 2
    assert event.detail["conflict_count"] == 0
    assert event.reason_codes == ("conflict_resolved",)


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_id": "not-a-uuid"},
        {"evidence_content_hash": "A" * 64},
        {"transition": "unchanged"},
        {"transition": "detected", "conflict_count": 0},
        {"transition": "detected", "previous_conflict_count": 1},
        {"transition": "resolved", "conflict_count": 1},
        {"transition": "resolved", "conflict_count": 0},
        {"occurred_at": datetime(2026, 8, 27, 12, 0)},
    ],
)
def test_invalid_conflict_observation_fails_closed(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "dataset_key": "equity.price.bar",
        "transition": "detected",
        "evidence_id": EVIDENCE_ID,
        "evidence_version": "1",
        "evidence_content_hash": "a" * 64,
        "conflict_count": 1,
        "previous_conflict_count": None,
        "previous_evidence_id": None,
        "previous_evidence_version": None,
        "previous_evidence_content_hash": None,
        "occurred_at": NOW,
        "recorded_at": NOW,
    }
    values.update(changes)

    with pytest.raises((TypeError, ValueError)):
        DataConflictAuditObservation(**values)


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
        assert stream_id == "data.conflict:equity.price.bar"
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


def test_append_binds_scope_sequences_transition_and_replays_first_winner() -> None:
    writer = _Writer()
    use_case = AppendDataConflictAuditObservationUseCase(writer, _ScopeProvider())

    detected = use_case.execute(_observation())
    replay = use_case.execute(_observation())
    resolved = use_case.execute(
        _observation(
            evidence_id=PREVIOUS_EVIDENCE_ID,
            transition="resolved",
            conflict_count=0,
            previous_conflict_count=1,
            previous_evidence_id=EVIDENCE_ID,
            previous_evidence_version="1",
            previous_evidence_content_hash="a" * 64,
        )
    )

    assert replay.event == detected.event
    assert resolved.event.sequence_no == 2
    assert resolved.event.predecessor_hash == detected.event.content_hash
    assert detected.event.scope == resolved.event.scope == SCOPE
    assert len(writer.events) == 2
