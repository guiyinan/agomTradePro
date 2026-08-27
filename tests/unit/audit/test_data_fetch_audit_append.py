"""Pure contract tests for the Data Center fetch audit append use case."""

from __future__ import annotations

import dataclasses
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from apps.audit.application.data_fetch_audit import (
    AppendDataFetchAuditObservationUseCase,
    DataFetchAuditObservation,
)
from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxConflict,
)
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
RAW_HASH = "a" * 64
SCOPE = AuditScopeRef("tenant:research", "owner:alice")


def _observation(*, scope: AuditScopeRef | None = None) -> DataFetchAuditObservation:
    """Build one valid immutable fetch observation."""

    return DataFetchAuditObservation(
        provider_key="provider-main",
        capability="macro.fetch",
        dataset_key="macro.fact",
        run_id="run-1",
        ingested_run_id="ingested-1",
        raw_audit_id="raw-1",
        raw_audit_version="1",
        raw_audit_content_hash=RAW_HASH,
        outcome=AuditOutcome.SUCCESS,
        row_count=2,
        recorded_at=NOW,
        occurred_at=NOW,
        scope=scope,
    )


class _ScopeProvider:
    def __init__(self, scope: AuditScopeRef) -> None:
        self.scope = scope
        self.as_of: list[datetime] = []

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        self.as_of.append(as_of)
        return self.scope


class _Atomic(AbstractContextManager[None]):
    def __init__(self, owner: _Writer) -> None:
        self.owner = owner

    def __enter__(self) -> None:
        self.owner.active += 1
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.owner.active -= 1
        return False


class _Writer:
    database_alias = "default"

    def __init__(self) -> None:
        self.active = 0
        self.events: list[SystemAuditEvent] = []
        self.append_calls: list[SystemAuditEvent] = []
        self.head: SystemAuditEvent | None = None
        self.conflict = False

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
        assert stream_id == "data.fetch:macro.fact"
        assert as_of == NOW
        assert scope == SCOPE
        return self.head

    def append_and_enqueue(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        assert self.active == 1
        assert expected_predecessor_hash == event.predecessor_hash
        assert recorded_at == NOW
        self.append_calls.append(event)
        if self.conflict:
            raise SystemAuditEventOutboxConflict("stream head changed")
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


def test_first_append_binds_authoritative_scope_and_writes_one_pair() -> None:
    writer = _Writer()
    scope_provider = _ScopeProvider(SCOPE)
    use_case = AppendDataFetchAuditObservationUseCase(writer, scope_provider)

    commit = use_case.execute(_observation())

    assert scope_provider.as_of == [NOW]
    assert len(writer.events) == 1
    assert len(writer.append_calls) == 1
    assert commit.event is writer.events[0]
    assert commit.event.scope == SCOPE
    assert commit.event.write_policy.value == "transactional_outbox"
    assert commit.event.evidence_refs[0].content_hash == RAW_HASH
    assert isinstance(commit.outbox_id, UUID)


def test_exact_replay_returns_first_winner_without_duplicate_event_or_outbox_append() -> None:
    writer = _Writer()
    use_case = AppendDataFetchAuditObservationUseCase(writer, _ScopeProvider(SCOPE))
    observation = _observation()

    first = use_case.execute(observation)
    replay = use_case.execute(observation)

    assert replay.event == first.event
    assert len(writer.events) == 1
    assert len(writer.append_calls) == 2


def test_conflicting_current_stream_head_is_rejected_fail_closed() -> None:
    writer = _Writer()
    use_case = AppendDataFetchAuditObservationUseCase(writer, _ScopeProvider(SCOPE))
    use_case.execute(observation := _observation())
    writer.events.clear()
    writer.head = use_case.execute(observation).event
    writer.conflict = True

    with pytest.raises(SystemAuditEventOutboxConflict, match="stream head changed"):
        use_case.execute(
            DataFetchAuditObservation(
                provider_key=observation.provider_key,
                capability=observation.capability,
                dataset_key=observation.dataset_key,
                run_id="run-2",
                ingested_run_id="ingested-2",
                raw_audit_id="raw-2",
                raw_audit_version="1",
                raw_audit_content_hash=RAW_HASH,
                outcome=AuditOutcome.SUCCESS,
                row_count=2,
                recorded_at=NOW,
                occurred_at=NOW,
            )
        )


def test_caller_scope_substitution_is_rejected() -> None:
    writer = _Writer()
    use_case = AppendDataFetchAuditObservationUseCase(writer, _ScopeProvider(SCOPE))

    with pytest.raises(ValueError, match="scope differs"):
        use_case.execute(_observation(scope=AuditScopeRef("tenant:other", "owner:alice")))

    assert writer.events == []


def test_same_run_allows_distinct_provider_fetch_events_without_idempotency_collision() -> None:
    writer = _Writer()
    use_case = AppendDataFetchAuditObservationUseCase(writer, _ScopeProvider(SCOPE))
    first = use_case.execute(_observation())
    writer.head = first.event

    second = use_case.execute(
        dataclasses.replace(
            _observation(),
            provider_key="provider-verifier",
            raw_audit_id="raw-2",
        )
    )

    assert second.event.event_id != first.event.event_id
    assert second.event.idempotency_key != first.event.idempotency_key
    assert second.event.predecessor_hash == first.event.content_hash
