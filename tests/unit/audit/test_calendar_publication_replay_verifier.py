from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from apps.audit.application.calendar_publication_audit import (
    CalendarPublicationAuditConflict,
    CalendarPublicationAuditCorruption,
    CalendarPublicationAuditDenied,
    CalendarPublicationPublishedObservation,
    build_calendar_publication_published_event,
)
from apps.audit.application.calendar_publication_replay_verifier import (
    CalendarPublicationAuditReplayReader,
    VerifyCurrentCalendarPublicationAuditReplayUseCase,
)
from apps.audit.application.system_audit_event_outbox import (
    ExactSystemAuditOutboxWinner,
    SystemAuditEventOutboxConflict,
)
from apps.audit.domain.calendar_publication_audit import (
    CalendarPublicationAuditEvidence,
    CalendarPublicationPublishedDetail,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from core.exceptions import AuthorizationError

DATASET = "exchange.calendar.days"
EXCHANGE = "SSE"
DB_ALIAS = "default"
PUBLISHED_AT = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


@dataclass
class FakePublisherPrincipal:
    """Mutable test lease implementing the live Audit publisher contract."""

    actor_type: str = "django_user"
    actor_id: str = "django-user:7"
    permission_codename: str = "publish_exchange_calendar"
    database_alias: str = DB_ALIAS
    verified_at: datetime = VERIFIED_AT
    user_id: int = 7
    live: bool = True
    assertions: int = 0

    def assert_live(self) -> None:
        """Count each live check and reject expired/revoked leases."""

        self.assertions += 1
        if not self.live:
            raise AuthorizationError("publisher lease has expired")


class FakeReplayReader:
    """Read-only fake port that enforces one caller-owned outer UOW."""

    database_alias = DB_ALIAS

    def __init__(
        self,
        *,
        event: SystemAuditEvent | None,
        outbox: ExactSystemAuditOutboxWinner | None,
        transaction_error: Exception | None = None,
    ) -> None:
        self.event = event
        self.outbox = outbox
        self.transaction_error = transaction_error
        self.in_transaction = False
        self.transaction_entries = 0
        self.stream_locks: list[str] = []
        self.event_queries: list[dict[str, object]] = []
        self.outbox_queries: list[SystemAuditEvent] = []

    @contextmanager
    def caller_owned_atomic(self) -> Iterator[None]:
        """Join one existing caller transaction without opening a nested one."""

        if self.in_transaction:
            raise SystemAuditEventOutboxConflict("nested fake transaction")
        if self.transaction_error is not None:
            raise self.transaction_error
        self.in_transaction = True
        self.transaction_entries += 1
        try:
            yield
        finally:
            self.in_transaction = False

    def lock_stream(self, stream_id: str) -> None:
        """Require the active caller transaction and retain the stream key."""

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
        """Record the exact selector and return only an event knowable then."""

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
        """Record a read for the exact event identity and return its pair."""

        assert self.in_transaction
        self.outbox_queries.append(event)
        return self.outbox


def _observation(
    *,
    recorded_at: datetime = PUBLISHED_AT,
    publication_hash: str = "3" * 64,
) -> CalendarPublicationPublishedObservation:
    """Build a typed persisted-publication expectation for verifier tests."""

    source_time = PUBLISHED_AT - timedelta(days=2)
    evidence = CalendarPublicationAuditEvidence(
        snapshot_id=str(uuid4()),
        exchange=EXCHANGE,
        coverage_start=date(2026, 10, 16),
        coverage_end=date(2026, 12, 31),
        provider_name="tushare",
        first_seen_at=source_time,
        snapshot_recorded_at=source_time + timedelta(seconds=1),
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
        response_completed_at=source_time,
        raw_provider_name="tushare",
        raw_dataset_key=DATASET,
        raw_transport="http-json",
    )
    detail = CalendarPublicationPublishedDetail(
        dataset_key=DATASET,
        exchange=EXCHANGE,
        publication_id="publication-001",
        publication_key="effective",
        policy_version="calendar-v1",
        publication_hash=publication_hash,
        snapshot_evidence=evidence,
    )
    return CalendarPublicationPublishedObservation(detail=detail, recorded_at=recorded_at)


def _principal(**changes: object) -> FakePublisherPrincipal:
    """Return a current authorized principal with selected test overrides."""

    principal = FakePublisherPrincipal()
    for name, value in changes.items():
        setattr(principal, name, value)
    return principal


def _event(
    observation: CalendarPublicationPublishedObservation,
    *,
    principal: FakePublisherPrincipal | None = None,
) -> SystemAuditEvent:
    """Build one valid immutable published event using the public builder."""

    return build_calendar_publication_published_event(
        observation,
        principal=principal or _principal(verified_at=observation.recorded_at),
        database_alias=DB_ALIAS,
        sequence_no=1,
        predecessor_hash=None,
    )


def _outbox(event: SystemAuditEvent) -> ExactSystemAuditOutboxWinner:
    """Build a value-validated outbox winner paired with an event."""

    return ExactSystemAuditOutboxWinner(
        outbox_id=uuid4(),
        event=event,
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        payload_hash=event.content_hash,
    )


def _use_case(
    reader: FakeReplayReader,
) -> VerifyCurrentCalendarPublicationAuditReplayUseCase:
    """Build the verifier through its read-only public port."""

    return VerifyCurrentCalendarPublicationAuditReplayUseCase(
        cast(CalendarPublicationAuditReplayReader, reader)
    )


def test_replay_returns_exact_historical_pair_with_current_same_actor_permission() -> None:
    observation = _observation()
    original_principal = _principal(verified_at=PUBLISHED_AT)
    persisted_event = _event(observation, principal=original_principal)
    persisted_outbox = _outbox(persisted_event)
    reader = FakeReplayReader(event=persisted_event, outbox=persisted_outbox)
    current_principal = _principal(verified_at=VERIFIED_AT)

    commit = _use_case(reader).execute(observation, principal=current_principal)

    assert commit.event is persisted_event
    assert commit.outbox_id == persisted_outbox.outbox_id
    assert commit.event_id == persisted_event.event_id
    assert commit.idempotency_key == persisted_event.idempotency_key
    assert reader.transaction_entries == 1
    assert reader.stream_locks == [persisted_event.stream_id]
    assert reader.event_queries[0]["as_of"] == VERIFIED_AT
    assert reader.outbox_queries == [persisted_event]
    assert not reader.in_transaction
    assert current_principal.assertions >= 2


@pytest.mark.parametrize(
    ("principal_changes", "error_type", "event_query_expected"),
    [
        (
            {"permission_codename": "view_exchange_calendar_publication_audit"},
            CalendarPublicationAuditDenied,
            False,
        ),
        ({"database_alias": "archive"}, CalendarPublicationAuditDenied, False),
        (
            {"actor_id": "django-user:8", "user_id": 8},
            CalendarPublicationAuditDenied,
            True,
        ),
        ({"actor_type": "service"}, CalendarPublicationAuditDenied, False),
        ({"verified_at": datetime(2026, 10, 17)}, CalendarPublicationAuditDenied, False),
        ({"live": False}, CalendarPublicationAuditDenied, False),
    ],
)
def test_replay_requires_live_current_publish_principal_and_same_original_user(
    principal_changes: dict[str, object],
    error_type: type[Exception],
    event_query_expected: bool,
) -> None:
    observation = _observation()
    event = _event(observation)
    reader = FakeReplayReader(event=event, outbox=_outbox(event))

    with pytest.raises(error_type):
        _use_case(reader).execute(observation, principal=_principal(**principal_changes))

    assert not reader.in_transaction
    assert bool(reader.event_queries) is event_query_expected
    assert reader.outbox_queries == []


def test_replay_rejects_missing_event_without_attempting_outbox_read_or_write() -> None:
    observation = _observation()
    reader = FakeReplayReader(event=None, outbox=None)

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(observation, principal=_principal())

    assert len(reader.event_queries) == 1
    assert reader.outbox_queries == []
    assert reader.transaction_entries == 1
    assert not reader.in_transaction


def test_replay_rejects_missing_exact_outbox_pair_without_repairing_it() -> None:
    observation = _observation()
    event = _event(observation)
    reader = FakeReplayReader(event=event, outbox=None)

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(observation, principal=_principal())

    assert reader.outbox_queries == [event]
    assert not reader.in_transaction


@pytest.mark.parametrize(
    "expected",
    [
        _observation(publication_hash="4" * 64),
        _observation(recorded_at=PUBLISHED_AT + timedelta(minutes=1)),
    ],
)
def test_replay_rejects_event_that_does_not_match_current_persisted_binding(
    expected: CalendarPublicationPublishedObservation,
) -> None:
    persisted = _observation()
    event = _event(persisted)
    reader = FakeReplayReader(event=event, outbox=_outbox(event))

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(expected, principal=_principal())

    assert reader.outbox_queries == []
    assert not reader.in_transaction


def test_replay_rejects_mismatched_outbox_event_even_when_its_own_hashes_are_valid() -> None:
    observation = _observation()
    event = _event(observation)
    other_actor_event = _event(
        observation, principal=_principal(actor_id="django-user:8", user_id=8)
    )
    reader = FakeReplayReader(event=event, outbox=_outbox(other_actor_event))

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(observation, principal=_principal())

    assert not reader.in_transaction


def test_replay_revalidates_mutated_outbox_winner_before_returning() -> None:
    observation = _observation()
    event = _event(observation)
    outbox = _outbox(event)
    object.__setattr__(outbox, "payload_hash", "0" * 64)
    reader = FakeReplayReader(event=event, outbox=outbox)

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(observation, principal=_principal())

    assert not reader.in_transaction


def test_replay_rejects_historical_event_not_yet_knowable_at_current_permission_cutoff() -> None:
    observation = _observation(recorded_at=VERIFIED_AT + timedelta(minutes=1))
    event = _event(observation, principal=_principal(verified_at=VERIFIED_AT))
    reader = FakeReplayReader(event=event, outbox=_outbox(event))

    with pytest.raises(CalendarPublicationAuditCorruption):
        _use_case(reader).execute(observation, principal=_principal())

    assert reader.event_queries[0]["as_of"] == VERIFIED_AT
    assert reader.outbox_queries == []


def test_replay_maps_caller_owned_transaction_failure_without_writing() -> None:
    observation = _observation()
    event = _event(observation)
    reader = FakeReplayReader(
        event=event,
        outbox=_outbox(event),
        transaction_error=SystemAuditEventOutboxConflict("not outermost"),
    )

    with pytest.raises(CalendarPublicationAuditConflict):
        _use_case(reader).execute(observation, principal=_principal())

    assert reader.event_queries == []
    assert reader.outbox_queries == []
