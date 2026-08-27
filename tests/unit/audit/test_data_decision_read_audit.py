"""RED contracts for canonical decision-read audit events."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from apps.audit.application.data_decision_read_audit import (
    AppendDataDecisionReadAuditObservationUseCase,
    DataDecisionReadAuditObservation,
    build_data_decision_read_audit_event,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import (
    AuditCategory,
    AuditOutcome,
    AuditScopeRef,
    AuditSeverity,
    AuditWritePolicy,
    SystemAuditEvent,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
PUBLICATION_HASH = "b" * 64
SCOPE = AuditScopeRef("tenant:research", "owner:alice")


def _observation(
    *,
    outcome: AuditOutcome = AuditOutcome.RECOVERED,
    dataset_key: str = "equity.price.bar",
    publication_key: str = "current",
    publication_id: str = "publication-1",
    publication_version: str = "1",
    publication_hash: str = PUBLICATION_HASH,
    provider_key: str = "provider-main",
    run_id: str = "run-1",
    ingested_run_id: str = "ingested-1",
    decision_key: str = "portfolio-readiness",
    freshness_status: str = "fresh",
    blocked_reason: str | None = None,
    scope: AuditScopeRef | None = None,
) -> DataDecisionReadAuditObservation:
    """Build one valid decision-read observation for contract tests."""

    return DataDecisionReadAuditObservation(
        dataset_key=dataset_key,
        publication_key=publication_key,
        publication_id=publication_id,
        publication_version=publication_version,
        publication_hash=publication_hash,
        provider_key=provider_key,
        run_id=run_id,
        ingested_run_id=ingested_run_id,
        decision_key=decision_key,
        freshness_status=freshness_status,
        outcome=outcome,
        recorded_at=NOW,
        occurred_at=NOW,
        blocked_reason=blocked_reason,
        scope=scope,
    )


def test_recovered_event_binds_publication_and_run_evidence() -> None:
    event = build_data_decision_read_audit_event(
        _observation(), sequence_no=1, predecessor_hash=None
    )

    assert event.event_type == "data.decision_read.recovered"
    assert event.category is AuditCategory.DATA_RELIABILITY
    assert event.outcome is AuditOutcome.RECOVERED
    assert event.write_policy is AuditWritePolicy.TRANSACTIONAL_OUTBOX
    assert event.severity is AuditSeverity.INFO
    assert event.dataset_key == "equity.price.bar"
    assert event.publication_id == "publication-1"
    assert event.resource is not None
    assert event.resource.resource_id == "publication-1"
    assert event.resource.resource_version == "1"
    assert event.correlations.run_id == "run-1"
    assert event.correlations.ingested_run_id == "ingested-1"
    assert event.correlations.publication_id == "publication-1"
    assert event.evidence_refs[0].artifact_id == "publication-1"
    assert event.evidence_refs[0].content_hash == PUBLICATION_HASH
    assert event.stream_id == "data.decision_read:equity.price.bar:current:portfolio-readiness"


def test_blocked_event_is_required_critical_and_redacted() -> None:
    event = build_data_decision_read_audit_event(
        _observation(
            outcome=AuditOutcome.BLOCKED,
            freshness_status="stale",
            blocked_reason="publication_stale",
        ),
        sequence_no=1,
        predecessor_hash=None,
    )

    assert event.event_type == "data.decision_read.blocked"
    assert event.outcome is AuditOutcome.BLOCKED
    assert event.write_policy is AuditWritePolicy.REQUIRED
    assert event.severity is AuditSeverity.CRITICAL
    assert "publication_stale" in event.reason_codes
    assert event.detail["freshness_status"] == "stale"
    assert "exception" not in str(event.detail).lower()
    assert "secret" not in str(event.detail).lower()
    assert event.publication_id == "publication-1"
    assert event.evidence_refs[0].content_hash == PUBLICATION_HASH


@pytest.mark.parametrize(
    "changes",
    [
        {"dataset_key": ""},
        {"publication_id": ""},
        {"publication_hash": "B" * 64},
        {"run_id": ""},
        {"ingested_run_id": ""},
        {"freshness_status": ""},
        {"outcome": AuditOutcome.BLOCKED},
        {"outcome": AuditOutcome.RECOVERED, "blocked_reason": "not_allowed"},
    ],
)
def test_invalid_observation_fields_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _observation(**changes)


def test_blocked_reason_rejects_exception_text() -> None:
    with pytest.raises(ValueError):
        _observation(
            outcome=AuditOutcome.BLOCKED,
            freshness_status="stale",
            blocked_reason="database password leaked",
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
        self.owner.active = True
        return None

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
        self.owner.active = False
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
        assert stream_id.startswith("data.decision_read:")
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


def test_append_binds_authority_and_exact_replay_is_one_event() -> None:
    writer = _Writer()
    scope_provider = _ScopeProvider(SCOPE)
    use_case = AppendDataDecisionReadAuditObservationUseCase(writer, scope_provider)
    observation = _observation()

    first = use_case.execute(observation)
    replay = use_case.execute(observation)

    assert scope_provider.as_of == [NOW, NOW]
    assert first.event.scope == SCOPE
    assert replay.event == first.event
    assert len(writer.events) == 1
    assert isinstance(first.outbox_id, UUID)


def test_repeated_same_state_is_idempotent_but_changed_state_is_new_identity() -> None:
    writer = _Writer()
    use_case = AppendDataDecisionReadAuditObservationUseCase(writer, _ScopeProvider(SCOPE))

    first = use_case.execute(_observation())
    same = use_case.execute(_observation())
    changed = use_case.execute(_observation(freshness_status="recovered"))

    assert same.event == first.event
    assert changed.event.event_id != first.event.event_id
    assert changed.event.idempotency_key != first.event.idempotency_key
    assert len(writer.events) == 2


def test_caller_scope_substitution_is_rejected() -> None:
    writer = _Writer()
    use_case = AppendDataDecisionReadAuditObservationUseCase(writer, _ScopeProvider(SCOPE))

    with pytest.raises(ValueError, match="scope"):
        use_case.execute(
            replace(_observation(), scope=AuditScopeRef("tenant:other", "owner:alice"))
        )

    assert writer.events == []
