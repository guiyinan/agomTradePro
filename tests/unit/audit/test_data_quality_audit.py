"""RED contracts for publication-bound data-quality transitions."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.audit.application.data_quality_audit import (
    AppendDataQualityAuditObservationUseCase,
    DataQualityAuditObservation,
    DataQualityStatusCount,
    build_data_quality_audit_event,
)
from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxConflict,
)
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
SCOPE = AuditScopeRef("tenant:research", "owner:alice")
PUBLICATION_HASH = "a" * 64


def _observation(
    *,
    quality_state: str = "accepted",
    member_count: int = 1,
    quality_status_counts: tuple[DataQualityStatusCount, ...] | None = None,
    publication_id: str = "publication-1",
    scope: AuditScopeRef | None = None,
) -> DataQualityAuditObservation:
    """Build one exact publication-bound quality observation."""

    counts = quality_status_counts
    if counts is None:
        counts = (
            DataQualityStatusCount(
                status="degraded" if quality_state == "degraded" else "accepted",
                count=member_count,
            ),
        )

    return DataQualityAuditObservation(
        dataset_key="equity.price.bar",
        publication_key="current",
        publication_id=publication_id,
        publication_version="1.0:1.0",
        publication_hash=PUBLICATION_HASH,
        provider_key="provider-main",
        run_id="run-1",
        ingested_run_id="ingested-1",
        quality_state=quality_state,
        member_count=member_count,
        quality_status_counts=counts,
        occurred_at=NOW,
        recorded_at=NOW,
        scope=scope,
    )


def test_quality_builder_suppresses_initial_accepted() -> None:
    """Initial accepted quality is healthy and emits no transition event."""

    assert (
        build_data_quality_audit_event(
            _observation(quality_state="accepted"),
            previous_quality_state=None,
            sequence_no=1,
            predecessor_hash=None,
        )
        is None
    )


def test_quality_builder_emits_detected_for_initial_degraded() -> None:
    """Initial degraded quality emits a warning transition with stable evidence."""

    event = build_data_quality_audit_event(
        _observation(quality_state="degraded", member_count=2),
        previous_quality_state=None,
        sequence_no=1,
        predecessor_hash=None,
    )
    assert event is not None
    assert event.event_type == "data.quality.changed"
    assert event.outcome is AuditOutcome.DETECTED
    assert event.severity.value == "warning"
    assert event.write_policy.value == "transactional_outbox"


@pytest.mark.parametrize(
    ("previous_quality_state", "quality_state", "outcome"),
    [
        ("accepted", "degraded", AuditOutcome.DETECTED),
        ("degraded", "accepted", AuditOutcome.RECOVERED),
    ],
)
def test_quality_builder_emits_only_real_detected_or_recovered_transitions(
    previous_quality_state: str,
    quality_state: str,
    outcome: AuditOutcome,
) -> None:
    """Quality changes map to detected or recovered outcomes."""

    event = build_data_quality_audit_event(
        _observation(
            quality_state=quality_state,
        ),
        previous_quality_state=previous_quality_state,
        sequence_no=2,
        predecessor_hash=PUBLICATION_HASH,
    )

    assert event is not None
    assert event.outcome is outcome
    assert event.event_type == "data.quality.changed"
    assert event.reason_codes == ("quality_changed",)


@pytest.mark.parametrize("quality_state", ["accepted", "degraded"])
def test_quality_builder_suppresses_same_state(quality_state: str) -> None:
    """Repeated normalized quality state does not append another event."""

    current = quality_state
    assert (
        build_data_quality_audit_event(
            _observation(quality_state=quality_state),
            previous_quality_state=current,
            sequence_no=2,
            predecessor_hash=PUBLICATION_HASH,
        )
        is None
    )


def test_quality_builder_preserves_exact_publication_correlations_and_scope() -> None:
    """The event binds dataset, publication, run, ingested run, evidence, and scope exactly."""

    event = build_data_quality_audit_event(
        _observation(quality_state="degraded", scope=SCOPE),
        previous_quality_state="accepted",
        sequence_no=2,
        predecessor_hash=PUBLICATION_HASH,
    )

    assert event is not None
    assert event.category.value == "data.reliability"
    assert event.correlations.dataset_key == "equity.price.bar"
    assert event.correlations.publication_id == "publication-1"
    assert event.correlations.run_id == "run-1"
    assert event.correlations.ingested_run_id == "ingested-1"
    assert event.resource is not None
    assert event.resource.resource_id == "publication-1"
    assert event.evidence_refs[0].artifact_id == "publication-1"
    assert event.evidence_refs[0].artifact_version == "1.0:1.0"
    assert event.evidence_refs[0].content_hash == PUBLICATION_HASH
    assert event.scope == SCOPE


class _ScopeProvider:
    """Typed authority fake for append tests."""

    def __init__(self) -> None:
        self.calls: list[datetime] = []
        self.current_scope = SCOPE
        self.fail = False

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        self.calls.append(as_of)
        if self.fail:
            raise PermissionError("quality scope has been revoked")
        return self.current_scope


class _Atomic(AbstractContextManager[None]):
    """Minimal transaction fake."""

    def __init__(self, writer: _Writer) -> None:
        self.writer = writer

    def __enter__(self) -> None:
        self.writer.active = True
        return None

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
        self.writer.active = False
        return False


class _Writer:
    """Typed first-winner/outbox fake with exact replay behavior."""

    database_alias = "default"

    def __init__(self, *, fail: bool = False) -> None:
        self.active = False
        self.fail = fail
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
        del as_of, scope
        return next(
            (event for event in reversed(self.events) if event.stream_id == stream_id),
            None,
        )

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
        if self.fail:
            raise RuntimeError("writer backend failure")
        winner = next((item for item in self.events if item.event_id == event.event_id), None)
        if winner is None:
            self.events.append(event)
            winner = event
        elif winner != event:
            raise ValueError("audit event identity already has another payload")
        return SystemAuditEventOutboxCommit(
            event=winner,
            outbox_id=uuid4(),
            event_id=winner.event_id,
            idempotency_key=winner.idempotency_key,
        )


def test_append_is_scoped_first_winner_and_exactly_replayable() -> None:
    """The append use case writes one outbox event and exact replay returns its winner."""

    writer = _Writer()
    use_case = AppendDataQualityAuditObservationUseCase(writer, _ScopeProvider())
    observation = _observation(quality_state="degraded")

    first = use_case.execute(observation)
    replay = use_case.execute(observation)

    assert first is not None
    assert replay is not None
    assert replay.event == first.event
    assert replay.idempotency_key == first.idempotency_key
    assert len(writer.events) == 1
    assert writer.events[0].scope == SCOPE


def test_append_replay_preserves_original_event_clock_after_current_scope_check() -> None:
    """An exact replay checks authority now while returning the first immutable event."""

    writer = _Writer()
    scope_provider = _ScopeProvider()
    use_case = AppendDataQualityAuditObservationUseCase(writer, scope_provider)
    observation = _observation(quality_state="degraded")

    first = use_case.execute(observation)
    replay = use_case.execute(replace(observation, recorded_at=NOW + timedelta(seconds=5)))

    assert first is not None
    assert replay is not None
    assert replay.event == first.event
    assert replay.event.recorded_at == NOW
    assert len(writer.events) == 1
    assert scope_provider.calls == [NOW, NOW + timedelta(seconds=5)]


def test_replay_rejects_changed_content_scope_and_revocation_without_append() -> None:
    """A replay cannot reuse an event after content changes or current authority is lost."""

    writer = _Writer()
    scope_provider = _ScopeProvider()
    use_case = AppendDataQualityAuditObservationUseCase(writer, scope_provider)
    observation = _observation(quality_state="degraded")

    first = use_case.execute(observation)
    assert first is not None
    persisted = tuple(writer.events)

    with pytest.raises(SystemAuditEventOutboxConflict, match="another observation"):
        use_case.execute(
            replace(
                observation,
                provider_key="provider-changed",
                recorded_at=NOW + timedelta(seconds=5),
            )
        )
    assert tuple(writer.events) == persisted

    scope_provider.current_scope = AuditScopeRef("tenant:research", "owner:bob")
    with pytest.raises(SystemAuditEventOutboxConflict, match="another observation"):
        use_case.execute(replace(observation, recorded_at=NOW + timedelta(seconds=10)))
    assert tuple(writer.events) == persisted

    scope_provider.fail = True
    with pytest.raises(PermissionError, match="scope has been revoked"):
        use_case.execute(replace(observation, recorded_at=NOW + timedelta(seconds=15)))

    assert tuple(writer.events) == persisted
    assert scope_provider.calls == [
        NOW,
        NOW + timedelta(seconds=5),
        NOW + timedelta(seconds=10),
        NOW + timedelta(seconds=15),
    ]


def test_append_propagates_writer_and_outbox_failure() -> None:
    """A required audit writer failure is visible to the caller and cannot be hidden."""

    use_case = AppendDataQualityAuditObservationUseCase(_Writer(fail=True), _ScopeProvider())

    with pytest.raises(RuntimeError, match="writer backend failure"):
        use_case.execute(_observation(quality_state="degraded"))
