"""RED contracts for canonical provider-health transition audit events."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from apps.audit.application.data_provider_health_audit import (
    AppendDataProviderHealthAuditObservationUseCase,
    DataProviderHealthAuditObservation,
    build_data_provider_health_audit_event,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import (
    AuditOutcome,
    AuditScopeRef,
    SystemAuditEvent,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
SNAPSHOT_HASH = "a" * 64
SCOPE = AuditScopeRef("tenant:research", "owner:alice")


def _observation(
    *,
    transition: str = "circuit_opened",
    outcome: AuditOutcome = AuditOutcome.BLOCKED,
    snapshot_hash: str = SNAPSHOT_HASH,
    scope: AuditScopeRef | None = None,
) -> DataProviderHealthAuditObservation:
    """Construct one provider-health transition contract fixture."""

    return DataProviderHealthAuditObservation(
        provider_key="provider-primary",
        capability="macro",
        dataset_key="macro.indicator",
        run_id="run-1",
        ingested_run_id="ingested-1",
        provider_health_snapshot_id="health-1",
        provider_health_snapshot_version="1",
        provider_health_snapshot_hash=snapshot_hash,
        transition=transition,
        reason_code=(
            "provider_circuit_opened" if transition == "circuit_opened" else "provider_recovered"
        ),
        outcome=outcome,
        occurred_at=NOW,
        recorded_at=NOW,
        scope=scope,
    )


def test_circuit_opened_is_required_critical_blocked_with_exact_evidence() -> None:
    """A circuit opening must publish the registered critical transition."""

    event = build_data_provider_health_audit_event(
        _observation(scope=SCOPE), sequence_no=1, predecessor_hash=None
    )

    assert event.event_type == "data.provider.circuit_opened"
    assert event.category.value == "data.reliability"
    assert event.outcome is AuditOutcome.BLOCKED
    assert event.write_policy.value == "required"
    assert event.severity.value == "critical"
    assert event.correlations.provider_key == "provider-primary"
    assert event.correlations.capability == "macro"
    assert event.correlations.run_id == "run-1"
    assert event.correlations.ingested_run_id == "ingested-1"
    assert event.evidence_refs[0].content_hash == SNAPSHOT_HASH
    assert event.scope == SCOPE


def test_recovered_is_info_and_transactional_outbox_with_stable_reason() -> None:
    """A real circuit recovery must be an idempotent outbox event."""

    event = build_data_provider_health_audit_event(
        _observation(
            transition="recovered",
            outcome=AuditOutcome.RECOVERED,
        ),
        sequence_no=2,
        predecessor_hash="b" * 64,
    )

    assert event.event_type == "data.provider.recovered"
    assert event.outcome is AuditOutcome.RECOVERED
    assert event.write_policy.value == "transactional_outbox"
    assert event.severity.value == "info"
    assert event.reason_codes == ("provider_recovered",)
    assert event.stream_id == "data.provider:provider-primary:macro"
    assert event.predecessor_hash == "b" * 64
    assert event.idempotency_key.startswith("data-provider-health:run-1:ingested-1:")


@pytest.mark.parametrize(
    "changes",
    [
        {"run_id": ""},
        {"ingested_run_id": ""},
        {"provider_health_snapshot_hash": "not-a-digest"},
        {"occurred_at": datetime(2026, 8, 27, 12, 0)},
        {"recorded_at": datetime(2026, 8, 27, 12, 0)},
        {"transition": "unknown"},
        {"reason_code": "secret=should-not-appear"},
    ],
)
def test_invalid_transition_observation_fails_closed(changes: dict[str, object]) -> None:
    """Identity, evidence, time, and transition corruption must be rejected."""

    with pytest.raises((TypeError, ValueError)):
        _observation(**changes)


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

    def __init__(self, *, substitute: bool = False, fail: bool = False) -> None:
        self.active = False
        self.events: list[SystemAuditEvent] = []
        self.substitute = substitute
        self.fail = fail

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
        assert stream_id == "data.provider:provider-primary:macro"
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
        if self.fail:
            raise RuntimeError("provider audit writer failed")
        existing = next((item for item in self.events if item.event_id == event.event_id), None)
        winner = existing or event
        if existing is None:
            self.events.append(event)
        committed_event = replace(winner, event_id="substituted") if self.substitute else winner
        return SystemAuditEventOutboxCommit(
            event=committed_event,
            outbox_id=uuid4(),
            event_id=committed_event.event_id,
            idempotency_key=committed_event.idempotency_key,
        )


def test_append_binds_scope_and_replays_the_exact_first_winner() -> None:
    """The append use case must bind scope and replay one exact event."""

    observation = _observation(scope=None)
    writer = _Writer()
    use_case = AppendDataProviderHealthAuditObservationUseCase(writer, _ScopeProvider())

    first = use_case.execute(observation)
    replay = use_case.execute(observation)

    assert replay.event == first.event
    assert replay.event.scope == SCOPE
    assert len(writer.events) == 1
    assert isinstance(first.outbox_id, UUID)


def test_writer_substitution_and_failure_are_not_hidden() -> None:
    with pytest.raises(ValueError, match="substituted"):
        AppendDataProviderHealthAuditObservationUseCase(
            _Writer(substitute=True), _ScopeProvider()
        ).execute(_observation())

    with pytest.raises(RuntimeError, match="writer failed"):
        AppendDataProviderHealthAuditObservationUseCase(
            _Writer(fail=True), _ScopeProvider()
        ).execute(_observation())
