"""Contract tests for canonical Data Center publication audit events."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from apps.audit.application.data_publication_audit import (
    AppendDataPublicationAuditObservationUseCase,
    DataPublicationAuditObservation,
    build_data_publication_audit_event,
)
from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxCommit,
)
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
PUBLICATION_HASH = "b" * 64
RAW_HASH = "a" * 64
SCOPE = AuditScopeRef("tenant:research", "owner:alice")


def _observation(
    *,
    outcome: AuditOutcome = AuditOutcome.PUBLISHED,
    member_count: int = 2,
    coverage_selected_count: int = 2,
    publication_hash: str = PUBLICATION_HASH,
    blocked_reason: str | None = None,
    error_class: str | None = None,
    scope: AuditScopeRef | None = None,
) -> DataPublicationAuditObservation:
    """Build one valid publication observation for the contract tests."""

    return DataPublicationAuditObservation(
        dataset_key="equity.price.bar",
        publication_key="current",
        publication_id="publication-1",
        publication_version="1",
        publication_hash=publication_hash,
        provider_key="provider-main",
        run_id="run-1",
        ingested_run_id="ingested-1",
        member_count=member_count,
        coverage_requested_count=2,
        coverage_eligible_count=coverage_selected_count,
        coverage_selected_count=coverage_selected_count,
        outcome=outcome,
        blocked_reason=blocked_reason,
        error_class=error_class,
        raw_audit_id="raw-1",
        raw_audit_version="1",
        raw_audit_content_hash=RAW_HASH,
        occurred_at=NOW,
        recorded_at=NOW,
        scope=scope,
    )


def test_published_event_has_required_policy_identity_and_evidence() -> None:
    event = build_data_publication_audit_event(_observation(), sequence_no=1, predecessor_hash=None)

    assert event.event_type == "data.publication.published"
    assert event.outcome is AuditOutcome.PUBLISHED
    assert event.write_policy.value == "required"
    assert event.dataset_key == "equity.price.bar"
    assert event.publication_id == "publication-1"
    assert event.resource is not None
    assert event.resource.resource_id == "publication-1"
    assert event.resource.resource_version == "1"
    assert event.evidence_refs[0].artifact_id == "raw-1"
    assert event.evidence_refs[0].content_hash == RAW_HASH
    assert event.correlations.run_id == "run-1"
    assert event.correlations.ingested_run_id == "ingested-1"


def test_blocked_event_requires_stable_reason_and_never_exposes_exception_text() -> None:
    event = build_data_publication_audit_event(
        _observation(
            outcome=AuditOutcome.BLOCKED,
            blocked_reason="coverage_incomplete",
            error_class="ValueError",
        ),
        sequence_no=1,
        predecessor_hash=None,
    )

    assert event.event_type == "data.publication.blocked"
    assert event.outcome is AuditOutcome.BLOCKED
    assert event.reason_codes == ("publication_blocked", "coverage_incomplete")
    assert "exception" not in str(event.detail).lower()
    assert event.detail["error_class"] == "ValueError"
    assert event.evidence_refs[0].content_hash == RAW_HASH


@pytest.mark.parametrize(
    "changes",
    [
        {"member_count": -1},
        {"coverage_selected_count": -1},
        {"member_count": 1, "coverage_selected_count": 2},
        {"publication_hash": "B" * 64},
        {"outcome": AuditOutcome.BLOCKED, "blocked_reason": None},
    ],
)
def test_invalid_publication_observations_fail_closed(changes: dict[str, object]) -> None:
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


def test_append_binds_authoritative_scope_and_exact_replay_is_idempotent() -> None:
    writer = _Writer()
    use_case = AppendDataPublicationAuditObservationUseCase(writer, _ScopeProvider())
    observation = _observation()

    first = use_case.execute(observation)
    replay = use_case.execute(observation)

    assert first.event.scope == SCOPE
    assert replay.event == first.event
    assert len(writer.events) == 1
    assert isinstance(first.outbox_id, UUID)
