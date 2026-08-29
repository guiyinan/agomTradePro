"""Contracts for publication-bound freshness state transitions."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.audit.application.data_freshness_audit import (
    AppendDataFreshnessAuditObservationUseCase,
    DataFreshnessAuditObservation,
    build_data_freshness_audit_event,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
SCOPE = AuditScopeRef("tenant:research", "owner:alice")


def _observation(
    *,
    publication_id: str = "publication-1",
    freshness_status: str = "fresh",
    must_not_use_for_decision: bool = False,
    blocked_reason: str | None = None,
) -> DataFreshnessAuditObservation:
    """Build one exact publication-bound freshness observation."""

    return DataFreshnessAuditObservation(
        dataset_key="equity.price.bar",
        publication_key="current",
        publication_id=publication_id,
        publication_version="1.0:1.0",
        publication_hash="a" * 64,
        provider_key="provider-main",
        run_id="run-1",
        ingested_run_id="ingested-1",
        freshness_status=freshness_status,
        must_not_use_for_decision=must_not_use_for_decision,
        blocked_reason=blocked_reason,
        occurred_at=NOW,
        recorded_at=NOW,
    )


def test_builder_preserves_exact_publication_and_transition_evidence() -> None:
    event = build_data_freshness_audit_event(
        _observation(),
        previous_freshness_status="unknown",
        previous_must_not_use_for_decision=None,
        previous_blocked_reason=None,
        sequence_no=1,
        predecessor_hash=None,
    )

    assert event.event_type == "data.freshness.changed"
    assert event.category.value == "data.reliability"
    assert event.outcome is AuditOutcome.RECOVERED
    assert event.write_policy.value == "transactional_outbox"
    assert event.severity.value == "warning"
    assert event.correlations.run_id == "run-1"
    assert event.correlations.publication_id == "publication-1"
    assert event.resource is not None
    assert event.resource.resource_id == "publication-1"
    assert event.evidence_refs[0].content_hash == "a" * 64
    assert event.detail["previous_freshness_status"] == "unknown"
    assert event.detail["freshness_status"] == "fresh"
    assert event.detail["previous_must_not_use_for_decision"] is None
    assert event.detail["must_not_use_for_decision"] is False
    assert event.reason_codes == ("freshness_changed",)


def test_blocked_transition_uses_stable_reason_without_error_text() -> None:
    event = build_data_freshness_audit_event(
        _observation(
            publication_id="publication-2",
            freshness_status="stale",
            must_not_use_for_decision=True,
            blocked_reason="canonical_publication_stale",
        ),
        previous_freshness_status="fresh",
        previous_must_not_use_for_decision=False,
        previous_blocked_reason=None,
        sequence_no=2,
        predecessor_hash="b" * 64,
    )

    assert event.outcome is AuditOutcome.BLOCKED
    assert event.detail["blocked_reason"] == "canonical_publication_stale"
    assert event.detail["previous_freshness_status"] == "fresh"
    assert "exception" not in str(event.detail).lower()
    assert "message" not in event.detail


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
        assert as_of == NOW
        assert scope == SCOPE
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


def test_append_derives_previous_state_and_suppresses_unchanged_observation() -> None:
    writer = _Writer()
    use_case = AppendDataFreshnessAuditObservationUseCase(writer, _ScopeProvider())

    first = use_case.execute(_observation())
    unchanged = use_case.execute(_observation(publication_id="publication-2"))
    changed = use_case.execute(
        _observation(
            publication_id="publication-3",
            freshness_status="stale",
            must_not_use_for_decision=True,
            blocked_reason="canonical_publication_stale",
        )
    )

    assert first is not None
    assert unchanged is None
    assert changed is not None
    assert len(writer.events) == 2
    assert changed.event.sequence_no == 2
    assert changed.event.predecessor_hash == first.event.content_hash
    assert changed.event.detail["previous_freshness_status"] == "fresh"
    assert changed.event.detail["previous_must_not_use_for_decision"] is False
    assert changed.event.scope == SCOPE


@pytest.mark.parametrize(
    "changes",
    [
        {"publication_hash": "A" * 64},
        {"freshness_status": "bad status"},
        {"must_not_use_for_decision": True, "blocked_reason": None},
        {"must_not_use_for_decision": False, "blocked_reason": "unexpected_block"},
        {"must_not_use_for_decision": True, "blocked_reason": "secret token"},
    ],
)
def test_invalid_freshness_observation_fails_closed(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "dataset_key": "equity.price.bar",
        "publication_key": "current",
        "publication_id": "publication-1",
        "publication_version": "1.0:1.0",
        "publication_hash": "a" * 64,
        "provider_key": "provider-main",
        "run_id": "run-1",
        "ingested_run_id": "ingested-1",
        "freshness_status": "fresh",
        "must_not_use_for_decision": False,
        "blocked_reason": None,
        "occurred_at": NOW,
        "recorded_at": NOW,
    }
    values.update(changes)

    with pytest.raises((TypeError, ValueError)):
        DataFreshnessAuditObservation(**values)
