from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from apps.audit.application.calendar_publication_audit import (
    CalendarPublicationAuditCorruption,
    CalendarPublicationAuditDenied,
    CalendarPublicationAuditValidationError,
    CalendarPublicationPublishedObservation,
    build_calendar_publication_published_event,
)
from apps.audit.application.calendar_publication_integrity import (
    CalendarPublicationAuditIntegrityReader,
    VerifyPublishedCalendarPublicationIntegrityUseCase,
)
from apps.audit.application.calendar_publication_replay_verifier import (
    CalendarPublicationAuditReplayReader,
    VerifyCurrentCalendarPublicationAuditReplayUseCase,
)
from apps.audit.application.system_audit_event_outbox import ExactSystemAuditOutboxWinner
from apps.audit.domain.calendar_publication_audit import (
    CalendarPublicationAuditEvidence,
    CalendarPublicationPublishedDetail,
)
from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditScopeRef,
    SystemAuditEvent,
)
from core.exceptions import AuthorizationError

DATASET = "exchange.calendar.days"
EXCHANGE = "SSE"
DB_ALIAS = "default"
PUBLISHED_AT = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
AS_OF = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


@dataclass
class FakePublisherPrincipal:
    """Mutable publisher lease for the separate same-actor replay check."""

    actor_type: str = "django_user"
    actor_id: str = "django-user:7"
    permission_codename: str = "publish_exchange_calendar"
    database_alias: str = DB_ALIAS
    verified_at: datetime = AS_OF
    user_id: int = 7
    live: bool = True

    def assert_live(self) -> None:
        """Reject an expired or revoked publisher lease."""

        if not self.live:
            raise AuthorizationError("publisher lease was revoked")


class FakeIntegrityReader:
    """Exact Audit selector fake with observable read-only transaction calls."""

    database_alias = DB_ALIAS

    def __init__(
        self,
        *,
        event: SystemAuditEvent | None,
        outbox: ExactSystemAuditOutboxWinner | None,
    ) -> None:
        self.event = event
        self.outbox = outbox
        self.in_transaction = False
        self.transaction_entries = 0
        self.stream_locks: list[str] = []
        self.event_queries: list[dict[str, object]] = []
        self.outbox_queries: list[SystemAuditEvent] = []
        self.write_calls = 0
        self.list_calls = 0

    @contextmanager
    def caller_owned_atomic(self) -> Iterator[None]:
        """Join one existing caller transaction without taking ownership."""

        if self.in_transaction:
            raise RuntimeError("nested transaction")
        self.in_transaction = True
        self.transaction_entries += 1
        try:
            yield
        finally:
            self.in_transaction = False

    def lock_stream(self, stream_id: str) -> None:
        """Record the exact stream lock taken inside the caller transaction."""

        assert self.in_transaction
        self.stream_locks.append(stream_id)

    def get_calendar_publication_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Return only the event knowable at the exact selector cutoff."""

        assert self.in_transaction
        self.event_queries.append(
            {
                "event_id": event_id,
                "event_version": event_version,
                "dataset_key": dataset_key,
                "exchange": exchange,
                "as_of": as_of,
            }
        )
        if self.event is None or self.event.recorded_at > as_of:
            return None
        return self.event

    def get_exact_outbox_winner_targeted(
        self,
        event: SystemAuditEvent,
    ) -> ExactSystemAuditOutboxWinner | None:
        """Return only the paired immutable outbox identity."""

        assert self.in_transaction
        self.outbox_queries.append(event)
        return self.outbox


def _observation(
    *,
    recorded_at: datetime = PUBLISHED_AT,
    publication_hash: str = "3" * 64,
) -> CalendarPublicationPublishedObservation:
    """Build one exact expected published snapshot and raw-response binding."""

    response_completed_at = PUBLISHED_AT - timedelta(days=2)
    evidence = CalendarPublicationAuditEvidence(
        snapshot_id=str(uuid4()),
        exchange=EXCHANGE,
        coverage_start=date(2026, 10, 16),
        coverage_end=date(2026, 12, 31),
        provider_name="tushare",
        first_seen_at=response_completed_at,
        snapshot_recorded_at=response_completed_at + timedelta(seconds=1),
        source_published_at=None,
        fact_content_hash="a" * 64,
        snapshot_content_hash="sha256:" + "b" * 64,
        snapshot_record_digest="sha256:" + "c" * 64,
        raw_payload_id=str(uuid4()),
        raw_payload_hash="sha256:" + "d" * 64,
        raw_record_digest="sha256:" + "e" * 64,
        raw_body_sha256="f" * 64,
        raw_retained_content_sha256="1" * 64,
        raw_request_scope_sha256="2" * 64,
        original_body_retained=True,
        response_completed_at=response_completed_at,
        raw_provider_name="tushare",
        raw_dataset_key=DATASET,
        raw_transport="egress",
    )
    detail = CalendarPublicationPublishedDetail(
        dataset_key=DATASET,
        exchange=EXCHANGE,
        publication_id="00000000-0000-0000-0000-000000000007",
        publication_key="exchange-calendar:SSE",
        policy_version="calendar-v1",
        publication_hash=publication_hash,
        snapshot_evidence=evidence,
    )
    return CalendarPublicationPublishedObservation(detail=detail, recorded_at=recorded_at)


def _event(observation: CalendarPublicationPublishedObservation) -> SystemAuditEvent:
    """Build the original persisted publication event without current permission."""

    principal = FakePublisherPrincipal(verified_at=observation.recorded_at)
    return build_calendar_publication_published_event(
        observation,
        principal=principal,
        database_alias=DB_ALIAS,
        sequence_no=1,
        predecessor_hash=None,
    )


def _outbox(event: SystemAuditEvent) -> ExactSystemAuditOutboxWinner:
    """Build the exact paired outbox winner."""

    return ExactSystemAuditOutboxWinner(
        outbox_id=uuid4(),
        event=event,
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        payload_hash=event.content_hash,
    )


def _rebuild_event(
    event: SystemAuditEvent,
    *,
    actor: AuditActorRef | None = None,
    scope: AuditScopeRef | None = None,
    recorded_at: datetime | None = None,
) -> SystemAuditEvent:
    """Recompute a valid envelope hash around one deliberate field mutation."""

    return SystemAuditEvent.create(
        event_id=event.event_id,
        event_version=event.event_version,
        schema_version=event.schema_version,
        category=event.category,
        event_type=event.event_type,
        owner=event.owner,
        write_policy=event.write_policy,
        outcome=event.outcome,
        severity=event.severity,
        reason_codes=event.reason_codes,
        occurred_at=event.occurred_at,
        recorded_at=recorded_at or event.recorded_at,
        observed_at=event.observed_at,
        actor=actor or event.actor,
        source_app=event.source_app,
        source_component=event.source_component,
        source_surface=event.source_surface,
        correlations=event.correlations,
        resource=event.resource,
        dataset_key=event.dataset_key,
        provider_key=event.provider_key,
        capability=event.capability,
        publication_id=event.publication_id,
        evidence_refs=event.evidence_refs,
        detail_schema=event.detail_schema,
        detail=event.detail,
        stream_id=event.stream_id,
        sequence_no=event.sequence_no,
        predecessor_hash=event.predecessor_hash,
        idempotency_key=event.idempotency_key,
        scope=scope,
    )


def _use_case(
    reader: FakeIntegrityReader,
) -> VerifyPublishedCalendarPublicationIntegrityUseCase:
    """Build the integrity checker from its exact read-only port."""

    return VerifyPublishedCalendarPublicationIntegrityUseCase(
        cast(CalendarPublicationAuditIntegrityReader, reader)
    )


def test_integrity_returns_minimal_exact_pair_without_requiring_original_actor_permission() -> None:
    observation = _observation()
    event = _event(observation)
    outbox = _outbox(event)
    reader = FakeIntegrityReader(event=event, outbox=outbox)

    receipt = _use_case(reader).execute(observation, as_of=AS_OF)

    assert receipt.event_id == event.event_id
    assert receipt.event_content_hash == event.content_hash
    assert receipt.actor_user_id == 7
    assert receipt.outbox_id == outbox.outbox_id
    assert receipt.idempotency_key == event.idempotency_key
    assert receipt.recorded_at == PUBLISHED_AT
    assert reader.transaction_entries == 1
    assert reader.event_queries[0]["as_of"] == AS_OF
    assert reader.stream_locks == [event.stream_id]
    assert reader.outbox_queries == [event]
    assert reader.write_calls == 0
    assert reader.list_calls == 0
    assert not reader.in_transaction


@pytest.mark.parametrize("missing", ["event", "outbox"])
def test_integrity_rejects_missing_event_or_outbox_without_repairing(
    missing: str,
) -> None:
    observation = _observation()
    event = _event(observation)
    reader = FakeIntegrityReader(
        event=None if missing == "event" else event,
        outbox=None if missing == "outbox" else _outbox(event),
    )

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(observation, as_of=AS_OF)

    assert reader.write_calls == 0
    assert reader.list_calls == 0
    assert not reader.in_transaction


def test_integrity_rejects_event_from_another_snapshot_or_publication_hash() -> None:
    expected = _observation()
    persisted_event = _event(_observation(publication_hash="4" * 64))
    reader = FakeIntegrityReader(event=persisted_event, outbox=_outbox(persisted_event))

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(expected, as_of=AS_OF)


@pytest.mark.parametrize(
    ("actor", "scope", "recorded_at"),
    [
        (None, AuditScopeRef("tenant-1", "owner-1"), None),
        (AuditActorRef("service", "calendar-publisher"), None, None),
        (None, None, PUBLISHED_AT + timedelta(hours=1)),
    ],
)
def test_integrity_rejects_wrong_scope_actor_or_recorded_time(
    actor: AuditActorRef | None,
    scope: AuditScopeRef | None,
    recorded_at: datetime | None,
) -> None:
    observation = _observation()
    valid_event = _event(observation)
    changed_event = _rebuild_event(valid_event, actor=actor, scope=scope, recorded_at=recorded_at)
    reader = FakeIntegrityReader(event=changed_event, outbox=_outbox(changed_event))

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(observation, as_of=AS_OF)


def test_integrity_rejects_hash_damage_and_non_exact_outbox_pair() -> None:
    observation = _observation()
    event = _event(observation)
    outbox = _outbox(event)
    damaged_event = event
    object.__setattr__(damaged_event, "content_hash", "0" * 64)
    reader = FakeIntegrityReader(event=damaged_event, outbox=outbox)

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(observation, as_of=AS_OF)


def test_integrity_rejects_outbox_hash_mismatch() -> None:
    observation = _observation()
    event = _event(observation)
    outbox = _outbox(event)
    object.__setattr__(outbox, "payload_hash", "0" * 64)
    reader = FakeIntegrityReader(event=event, outbox=outbox)

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(observation, as_of=AS_OF)


def test_integrity_rejects_future_cutoff_regression_before_selector_reads() -> None:
    observation = _observation()
    event = _event(observation)
    reader = FakeIntegrityReader(event=event, outbox=_outbox(event))

    with pytest.raises(CalendarPublicationAuditValidationError):
        _use_case(reader).execute(observation, as_of=PUBLISHED_AT - timedelta(microseconds=1))

    assert reader.event_queries == []
    assert reader.outbox_queries == []


def test_current_replay_still_requires_live_publish_permission_after_integrity_succeeds() -> None:
    observation = _observation()
    event = _event(observation)
    reader = FakeIntegrityReader(event=event, outbox=_outbox(event))
    _use_case(reader).execute(observation, as_of=AS_OF)
    revoked_principal = FakePublisherPrincipal(live=False)

    with pytest.raises(CalendarPublicationAuditDenied):
        VerifyCurrentCalendarPublicationAuditReplayUseCase(
            cast(CalendarPublicationAuditReplayReader, reader)
        ).execute(observation, principal=revoked_principal)
