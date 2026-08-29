"""RED contracts for canonical repair-parent audit events."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from apps.audit.application.data_repair_audit import (
    AppendDataRepairAuditObservationUseCase,
    DataRepairAuditObservation,
    RepairPublicationEvidence,
    RepairSectionEvidence,
    build_data_repair_audit_event,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent
from apps.data_center.application.sync_identity import build_sync_execution_identity

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
RUN_ID = str(uuid4())
INGESTED_RUN_ID = str(uuid4())
PUBLICATION_HASH = "b" * 64
SCOPE = AuditScopeRef("tenant:research", "owner:alice")
IDENTITY = build_sync_execution_identity(
    run_id=RUN_ID,
    ingested_run_id=INGESTED_RUN_ID,
    batch_id=str(uuid4()),
    dataset_key="decision.reliability.repair",
    provider_name="data-center-repair",
)


def _publication(
    *,
    publication_id: str | None = None,
    dataset_key: str = "equity.price.bar",
    publication_hash: str = PUBLICATION_HASH,
) -> RepairPublicationEvidence:
    """Construct one exact publication evidence reference."""

    return RepairPublicationEvidence(
        publication_id=publication_id or str(uuid4()),
        publication_version="7",
        publication_hash=publication_hash,
        dataset_key=dataset_key,
    )


def _observation(
    *,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    publications: tuple[RepairPublicationEvidence, ...] = (),
    scope: AuditScopeRef | None = None,
    occurred_at: datetime = NOW,
    recorded_at: datetime = NOW,
) -> DataRepairAuditObservation:
    """Construct one valid repair completion observation."""

    return DataRepairAuditObservation(
        identity=IDENTITY,
        target_date=date(2026, 8, 27),
        sections=_sections(outcome),
        publications=publications,
        outcome=outcome,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        scope=scope,
    )


def _sections(outcome: AuditOutcome) -> tuple[RepairSectionEvidence, ...]:
    """Return a section summary consistent with the requested parent outcome."""

    if outcome is AuditOutcome.FAILED:
        status = "failed"
        blocked = True
    elif outcome is AuditOutcome.PARTIAL:
        status = "blocked"
        blocked = True
    else:
        status = "ready"
        blocked = False
    return (
        RepairSectionEvidence(
            section_key="macro",
            status=status,
            must_not_use_for_decision=blocked,
            remaining_blocker_count=1 if blocked else 0,
        ),
    )


def test_success_repair_event_preserves_identity_and_publication_evidence() -> None:
    """Successful repair emits required event with exact chain evidence."""

    publication = _publication()
    event = build_data_repair_audit_event(
        _observation(publications=(publication,), scope=SCOPE),
        sequence_no=1,
        predecessor_hash=None,
    )

    assert event.event_type == "data.repair.completed"
    assert event.category.value == "data.reliability"
    assert event.outcome is AuditOutcome.SUCCESS
    assert event.write_policy.value == "required"
    assert event.severity.value == "info"
    assert event.correlations.run_id == RUN_ID
    assert event.correlations.ingested_run_id == INGESTED_RUN_ID
    assert event.correlations.dataset_key == "decision.reliability.repair"
    assert event.scope == SCOPE
    assert event.detail["sync_identity_id"] == IDENTITY.identity_hash
    assert event.detail["sync_identity_version"] == "1"
    assert event.detail["sync_identity_hash"] == IDENTITY.identity_hash
    assert event.evidence_refs[0].artifact_type == "sync_execution_identity"
    assert event.evidence_refs[0].artifact_id == IDENTITY.identity_hash
    assert event.evidence_refs[0].content_hash == IDENTITY.identity_hash
    assert event.detail["publications"] == [
        {
            "publication_id": publication.publication_id,
            "publication_version": "7",
            "publication_hash": PUBLICATION_HASH,
            "dataset_key": "equity.price.bar",
        }
    ]
    assert event.detail["sections"] == [
        {
            "section_key": "macro",
            "status": "ready",
            "must_not_use_for_decision": False,
            "remaining_blocker_count": 0,
        }
    ]


@pytest.mark.parametrize(
    ("outcome", "expected_severity"),
    [
        (AuditOutcome.SUCCESS, "info"),
        (AuditOutcome.PARTIAL, "info"),
        (AuditOutcome.FAILED, "info"),
    ],
)
def test_all_repair_outcomes_map_to_registered_completion_event(
    outcome: AuditOutcome, expected_severity: str
) -> None:
    """Success, partial, and failed repairs retain the required policy."""

    event = build_data_repair_audit_event(
        _observation(outcome=outcome), sequence_no=1, predecessor_hash=None
    )

    assert event.event_type == "data.repair.completed"
    assert event.outcome is outcome
    assert event.write_policy.value == "required"
    assert event.severity.value == expected_severity


@pytest.mark.parametrize(
    "changes",
    [
        {"occurred_at": datetime(2026, 8, 27, 12, 0)},
        {"recorded_at": datetime(2026, 8, 27, 12, 0)},
    ],
)
def test_invalid_repair_timestamps_fail_closed(
    changes: dict[str, object],
) -> None:
    """Naive authoritative timestamps are rejected."""

    with pytest.raises((TypeError, ValueError)):
        _observation(**changes)


def test_invalid_identity_type_fails_closed() -> None:
    """The parent must reference a validated canonical execution identity."""

    with pytest.raises((TypeError, ValueError)):
        DataRepairAuditObservation(
            identity=object(),  # type: ignore[arg-type]
            target_date=date(2026, 8, 27),
            sections=_sections(AuditOutcome.SUCCESS),
            publications=(),
            outcome=AuditOutcome.SUCCESS,
            occurred_at=NOW,
            recorded_at=NOW,
        )


def test_duplicate_publication_identity_fails_closed() -> None:
    """One parent cannot claim the same canonical publication twice."""

    publication = _publication()
    with pytest.raises((TypeError, ValueError)):
        _observation(publications=(publication, publication))


def test_mixed_dataset_publications_are_preserved_in_canonical_order() -> None:
    """One repair run can produce macro, quote, and price publications."""

    quote = _publication(dataset_key="equity.quote.snapshot")
    price = _publication(dataset_key="equity.price.bar")

    event = build_data_repair_audit_event(
        _observation(publications=(quote, price)),
        sequence_no=1,
        predecessor_hash=None,
    )

    assert {item["dataset_key"] for item in event.detail["publications"]} == {
        "equity.quote.snapshot",
        "equity.price.bar",
    }
    assert {reference.artifact_id for reference in event.evidence_refs[1:]} == {
        quote.publication_id,
        price.publication_id,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"publication_id": "not-a-uuid"},
        {"publication_version": ""},
        {"publication_hash": "A" * 64},
        {"dataset_key": ""},
    ],
)
def test_invalid_publication_evidence_fails_closed(changes: dict[str, str]) -> None:
    """Malformed exact publication evidence is rejected at construction."""

    values = {
        "publication_id": str(uuid4()),
        "publication_version": "7",
        "publication_hash": PUBLICATION_HASH,
        "dataset_key": "equity.price.bar",
    }
    values.update(changes)
    with pytest.raises((TypeError, ValueError)):
        RepairPublicationEvidence(**values)


class _ScopeProvider:
    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        assert as_of == NOW
        return SCOPE


class _Atomic(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
        return False


class _Writer:
    database_alias = "default"

    def __init__(self) -> None:
        self.events: list[SystemAuditEvent] = []

    def atomic(self) -> AbstractContextManager[None]:
        return _Atomic()

    def get_winner(
        self, *, event_id: str, event_version: str, as_of: datetime
    ) -> SystemAuditEvent | None:
        del event_version, as_of
        return next((event for event in self.events if event.event_id == event_id), None)

    def get_current_head(
        self, *, stream_id: str, as_of: datetime, scope: AuditScopeRef
    ) -> SystemAuditEvent | None:
        del stream_id, as_of, scope
        return self.events[-1] if self.events else None

    def append_and_enqueue(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        del expected_predecessor_hash, recorded_at
        winner = next((item for item in self.events if item.event_id == event.event_id), event)
        if winner is event:
            self.events.append(event)
        return SystemAuditEventOutboxCommit(
            event=winner,
            outbox_id=uuid4(),
            event_id=winner.event_id,
            idempotency_key=winner.idempotency_key,
        )


def test_append_replays_exact_winner_and_preserves_stream_predecessor() -> None:
    """Repair append is idempotent and uses the authoritative scope."""

    writer = _Writer()
    use_case = AppendDataRepairAuditObservationUseCase(writer, _ScopeProvider())
    observation = _observation(scope=None)

    first = use_case.execute(observation)
    replay = use_case.execute(observation)

    assert first.event.scope == SCOPE
    assert replay.event == first.event
    assert len(writer.events) == 1


def test_append_writer_exception_is_not_exposed_or_swallowed() -> None:
    """Underlying writer failures must propagate without credential text."""

    class _FailingWriter(_Writer):
        def append_and_enqueue(
            self,
            event: SystemAuditEvent,
            *,
            expected_predecessor_hash: str | None,
            recorded_at: datetime,
        ) -> SystemAuditEventOutboxCommit:
            del event, expected_predecessor_hash, recorded_at
            raise RuntimeError("writer failed")

    use_case = AppendDataRepairAuditObservationUseCase(_FailingWriter(), _ScopeProvider())

    with pytest.raises(RuntimeError, match="writer failed"):
        use_case.execute(_observation())
