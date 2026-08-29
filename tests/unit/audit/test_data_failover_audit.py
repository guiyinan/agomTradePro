"""RED contract tests for canonical Data Center failover audit events."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from apps.audit.application.data_failover_audit import (
    AppendDataFailoverAuditObservationUseCase,
    DataFailoverAuditObservation,
    build_data_failover_audit_event,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef, SystemAuditEvent

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
RAW_HASH = "a" * 64
SCOPE = AuditScopeRef("tenant:research", "owner:alice")


def _observation(
    *,
    to_provider: str = "provider-backup",
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    tolerance: float = 0.01,
    observed_deviation: float | None = 0.005,
    reason_code: str = "failover_completed",
    error_class: str | None = None,
    raw_audit_content_hash: str = RAW_HASH,
    scope: AuditScopeRef | None = None,
) -> DataFailoverAuditObservation:
    """Build one valid accepted or blocked failover observation."""

    return DataFailoverAuditObservation(
        dataset_key="equity.price.bar",
        capability="historical_price",
        from_provider="provider-primary",
        to_provider=to_provider,
        run_id="run-1",
        ingested_run_id="ingested-1",
        raw_audit_id="raw-1",
        raw_audit_version="1",
        raw_audit_content_hash=raw_audit_content_hash,
        tolerance=tolerance,
        observed_deviation=observed_deviation,
        reason_code=reason_code,
        error_class=error_class,
        outcome=outcome,
        occurred_at=NOW,
        recorded_at=NOW,
        scope=scope,
    )


def test_succeeded_switch_builds_registered_event_with_exact_evidence() -> None:
    event = build_data_failover_audit_event(_observation(), sequence_no=1, predecessor_hash=None)

    assert event.event_type == "data.failover.succeeded"
    assert event.category.value == "data.reliability"
    assert event.outcome is AuditOutcome.SUCCESS
    assert event.write_policy.value == "transactional_outbox"
    assert event.correlations.run_id == "run-1"
    assert event.correlations.ingested_run_id == "ingested-1"
    assert event.correlations.provider_key == "provider-backup"
    assert event.evidence_refs[0].artifact_id == "raw-1"
    assert event.evidence_refs[0].content_hash == RAW_HASH
    assert event.stream_id == "data.failover:equity.price.bar"
    assert event.idempotency_key.startswith("data-failover:run-1:ingested-1:")


def test_blocked_switch_has_stable_reason_and_no_exception_or_secret_message() -> None:
    event = build_data_failover_audit_event(
        _observation(
            to_provider="provider-backup",
            outcome=AuditOutcome.BLOCKED,
            observed_deviation=0.25,
            reason_code="failover_rejected",
            error_class="ConsistencyError",
        ),
        sequence_no=1,
        predecessor_hash=None,
    )

    assert event.event_type == "data.failover.rejected"
    assert event.outcome is AuditOutcome.BLOCKED
    assert event.reason_codes == ("failover_rejected",)
    assert event.detail["error_class"] == "ConsistencyError"
    assert "exception" not in str(event.detail).lower()
    assert "message" not in event.detail
    assert "secret" not in str(event.detail).lower()


def test_started_and_exhausted_switches_match_registered_taxonomy() -> None:
    started = build_data_failover_audit_event(
        _observation(
            outcome=AuditOutcome.STARTED,
            observed_deviation=None,
            reason_code="primary_unavailable",
        ),
        sequence_no=1,
        predecessor_hash=None,
    )
    exhausted = build_data_failover_audit_event(
        _observation(
            outcome=AuditOutcome.BLOCKED,
            observed_deviation=None,
            reason_code="failover_consistency_evidence_missing",
            error_class="ConsistencyEvidenceUnavailable",
        ),
        sequence_no=2,
        predecessor_hash=started.content_hash,
    )

    assert started.event_type == "data.failover.started"
    assert started.outcome is AuditOutcome.STARTED
    assert started.reason_codes == ("failover_started",)
    assert exhausted.event_type == "data.failover.exhausted"
    assert exhausted.write_policy.value == "required"
    assert exhausted.reason_codes == ("failover_exhausted",)


@pytest.mark.parametrize(
    "changes",
    [
        {"raw_audit_content_hash": "A" * 64},
        {"raw_audit_content_hash": "not-a-hash"},
        {"tolerance": -0.01},
        {"tolerance": 1.01},
        {"observed_deviation": -0.01},
        {"outcome": AuditOutcome.SUCCESS, "observed_deviation": None},
        {"outcome": AuditOutcome.SUCCESS, "observed_deviation": 0.02},
        {"outcome": AuditOutcome.STARTED, "observed_deviation": 0.01},
        {"outcome": AuditOutcome.STARTED, "observed_deviation": None, "error_class": "Error"},
        {"reason_code": "Bad Reason"},
        {"error_class": "ValueError: secret=token"},
        {"outcome": AuditOutcome.BLOCKED, "error_class": ""},
    ],
)
def test_invalid_failover_observation_fails_closed(changes: dict[str, object]) -> None:
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
        assert stream_id == "data.failover:equity.price.bar"
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


def test_append_binds_authoritative_scope_and_replays_the_first_winner() -> None:
    writer = _Writer()
    use_case = AppendDataFailoverAuditObservationUseCase(writer, _ScopeProvider())
    observation = _observation()

    first = use_case.execute(observation)
    replay = use_case.execute(observation)

    assert first.event.scope == SCOPE
    assert replay.event == first.event
    assert len(writer.events) == 1
    assert isinstance(first.outbox_id, UUID)
