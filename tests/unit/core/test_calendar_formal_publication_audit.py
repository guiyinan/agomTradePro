from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from apps.audit.application.calendar_publication_audit import CalendarPublicationAuditUnavailable
from apps.audit.application.system_audit_event_outbox import (
    ExactSystemAuditOutboxWinner,
    SystemAuditEventOutboxCommit,
)
from apps.audit.calendar_publication_composition import CalendarPublicationAuditCoordinator
from apps.audit.domain.calendar_publication_audit import (
    CalendarPublicationPublishedDetail,
    validate_calendar_publication_event,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.data_center.application.calendar_publication_authority import (
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
)
from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CalendarNullableMemberCodecVersion,
    CalendarPublicationMemberReference,
    PublicationMember,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarDay,
    ExchangeCalendarRawReference,
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotCandidate,
    exchange_calendar_request_scope_hash,
    make_exchange_calendar_snapshot,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationRecord,
    create_calendar_formal_publication_seal,
)
from core.exceptions import AuthorizationError
from core.integration.calendar_formal_publication_audit import (
    CoreCalendarFormalPublicationAuditBridge,
)

DB_ALIAS = "default"
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
DATASET = DatasetKey("exchange.calendar.days", "1.0", "1.0")
CALENDAR_DATE = date(2026, 10, 16)


@dataclass
class FakePrincipal:
    """Mutable in-memory equivalent of the lock-scoped Data Center principal."""

    actor_type: str = "django_user"
    actor_id: str = "django-user:7"
    permission_codename: str = "publish_exchange_calendar"
    database_alias: str = DB_ALIAS
    user_id: int = 7
    permission_id: int = 31
    verified_at: datetime = NOW - timedelta(seconds=1)
    live: bool = True
    assertions: int = 0

    def assert_live(self) -> None:
        """Count lease checks and reject a revoked principal."""

        self.assertions += 1
        if not self.live:
            raise AuthorizationError("publisher lease was revoked")


class FakeCoordinator:
    """In-memory Audit coordinator that requires a caller-owned outer UOW."""

    database_alias = DB_ALIAS

    def __init__(self) -> None:
        self.outer_active = False
        self.reader_active = False
        self.transaction_entries = 0
        self.stream_locks: list[str] = []
        self.event_queries: list[dict[str, object]] = []
        self.outbox_queries: list[SystemAuditEvent] = []
        self.events: dict[str, SystemAuditEvent] = {}
        self.outboxes: dict[str, ExactSystemAuditOutboxWinner] = {}
        self.write_calls = 0
        self.list_calls = 0

    @contextmanager
    def outer_transaction(self) -> Iterator[None]:
        """Model the Data Center repository's one caller-owned transaction."""

        if self.outer_active:
            raise RuntimeError("outer transaction cannot nest")
        self.outer_active = True
        try:
            yield
        finally:
            self.outer_active = False

    @contextmanager
    def caller_owned_atomic(self) -> Iterator[None]:
        """Assert Audit joins the existing outer transaction without nesting."""

        if not self.outer_active or self.reader_active:
            raise RuntimeError("Audit requires the existing outer transaction")
        self.reader_active = True
        self.transaction_entries += 1
        try:
            yield
        finally:
            self.reader_active = False

    def lock_stream(self, stream_id: str) -> None:
        """Record the exact event-stream serialization lock."""

        assert self.reader_active
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
        """Return only the deterministic publication event visible at cutoff."""

        assert self.reader_active
        self.event_queries.append(
            {
                "event_id": event_id,
                "event_version": event_version,
                "dataset_key": dataset_key,
                "exchange": exchange,
                "as_of": as_of,
            }
        )
        event = self.events.get(event_id)
        if event is None or event.recorded_at > as_of:
            return None
        return event

    def get_calendar_publication_head_targeted(
        self,
        *,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Return a selected stream head, or none before the first append."""

        assert self.reader_active
        selected = [
            event
            for event in self.events.values()
            if event.dataset_key == dataset_key
            and event.recorded_at <= as_of
            and event.stream_id in self.stream_locks
        ]
        return max(selected, key=lambda event: event.sequence_no) if selected else None

    def get_exact_outbox_winner_targeted(
        self,
        event: SystemAuditEvent,
    ) -> ExactSystemAuditOutboxWinner | None:
        """Return the exact outbox row associated with the event identity."""

        assert self.reader_active
        self.outbox_queries.append(event)
        return self.outboxes.get(event.event_id)

    def append_and_enqueue_calendar_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        principal: FakePrincipal,
    ) -> SystemAuditEventOutboxCommit:
        """Store the exact event/outbox pair while the outer transaction is open."""

        assert self.reader_active
        assert self.outer_active
        principal.assert_live()
        assert event.recorded_at == recorded_at
        assert event.predecessor_hash == expected_predecessor_hash
        self.write_calls += 1
        self.events[event.event_id] = event
        outbox = ExactSystemAuditOutboxWinner(
            outbox_id=uuid4(),
            event=event,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            payload_hash=event.content_hash,
        )
        self.outboxes[event.event_id] = outbox
        return SystemAuditEventOutboxCommit(
            event=event,
            outbox_id=outbox.outbox_id,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
        )


def _snapshot() -> ExchangeCalendarSnapshot:
    """Build one complete source-bound calendar snapshot with unknown source time."""

    first_seen = NOW - timedelta(minutes=2)
    raw = ExchangeCalendarRawReference(
        payload_id=str(uuid4()),
        payload_hash="sha256:" + "1" * 64,
        record_digest="sha256:" + "2" * 64,
        body_sha256="3" * 64,
        retained_content_sha256="3" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            "SSE", CALENDAR_DATE, CALENDAR_DATE
        ),
        original_body_retained=True,
        response_completed_at=first_seen,
        provider_name="tushare",
        dataset_key=DATASET.value,
        transport="egress",
    )
    candidate = ExchangeCalendarSnapshotCandidate(
        exchange="SSE",
        coverage_start=CALENDAR_DATE,
        coverage_end=CALENDAR_DATE,
        days=(
            ExchangeCalendarDay(
                exchange="SSE",
                calendar_date=CALENDAR_DATE,
                is_open=True,
                previous_open_date=date(2026, 10, 15),
            ),
        ),
        provider_name="tushare",
        raw_reference=raw,
        first_seen_at=first_seen,
        source_published_at=None,
    )
    return make_exchange_calendar_snapshot(
        candidate,
        snapshot_id=str(uuid4()),
        recorded_at=first_seen + timedelta(seconds=1),
    )


def _record(
    *,
    published_at: datetime = NOW,
    snapshot: ExchangeCalendarSnapshot | None = None,
) -> CalendarFormalPublicationRecord:
    """Build the exact seal and current record used by the bridge tests."""

    selected = snapshot or _snapshot()
    policy = PublicationPolicy(
        dataset=DATASET,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "fetched_at", "fact_content_hash"),
        retention_days=3650,
        policy_version="calendar-policy-v1",
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    member = PublicationMember(
        member_id="member-1",
        publication_id="publication-placeholder",
        dataset_key=DATASET.value,
        natural_key=f"SSE:{CALENDAR_DATE.isoformat()}:{CALENDAR_DATE.isoformat()}",
        source="tushare",
        source_record_id=selected.snapshot_id,
        fact_table="data_center_exchange_calendar_snapshot_fact",
        fact_pk=selected.snapshot_id,
        observed_at=None,
        raw_payload_hash=selected.raw_reference.payload_hash,
        quality_status="accepted",
        revision_number=1,
        available_at=None,
        fetched_at=selected.first_seen_at,
        source_published_at=None,
        raw_payload_scope="record_response_body",
        fact_content_hash="a" * 64,
    )
    member_reference = CalendarPublicationMemberReference(
        member=member,
        snapshot_content_hash=selected.content_hash,
        snapshot_record_digest=selected.record_digest,
        codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    seal = create_calendar_formal_publication_seal(
        dataset=DATASET,
        exchange="SSE",
        calendar_response_max_age_seconds=3600,
        contract_recorded_at=NOW - timedelta(days=2),
        policy=policy,
        policy_recorded_at=NOW - timedelta(days=1),
        snapshot=selected,
        member_reference=member_reference,
    )
    return CalendarFormalPublicationRecord(
        seal=seal,
        publication_id=str(uuid4()),
        activation_id="activation-1",
        lifecycle=CalendarPublicationLifecycle.PUBLISHED,
        published_at=published_at,
    )


def _bridge(coordinator: FakeCoordinator) -> CoreCalendarFormalPublicationAuditBridge:
    """Build the bridge using one explicit alias-bound Audit App coordinator."""

    return CoreCalendarFormalPublicationAuditBridge(
        using=DB_ALIAS,
        coordinator=cast(CalendarPublicationAuditCoordinator, coordinator),
    )


def _principal(**changes: object) -> FakePrincipal:
    """Return a live exact session-backed principal with selected test changes."""

    principal = FakePrincipal()
    for name, value in changes.items():
        setattr(principal, name, value)
    return principal


def test_publish_maps_exact_source_evidence_and_appends_inside_caller_transaction() -> None:
    coordinator = FakeCoordinator()
    bridge = _bridge(coordinator)
    record = _record()
    principal = _principal()

    with coordinator.outer_transaction():
        pair = bridge.record_published(
            record, principal=cast(LockedCalendarPublisherPrincipal, principal)
        )

    event = coordinator.events[pair.event_id]
    validate_calendar_publication_event(event)
    assert pair.database_alias == DB_ALIAS
    assert pair.dataset_key == DATASET.value
    assert pair.exchange == "SSE"
    assert pair.publication_id == record.publication_id
    assert pair.publication_hash == record.seal.publication_hash
    assert pair.actor_user_id == principal.user_id
    assert pair.recorded_at == record.published_at
    assert pair.event_content_hash == event.content_hash
    assert pair.outbox_id == coordinator.outboxes[event.event_id].outbox_id
    assert event.observed_at is None
    detail = CalendarPublicationPublishedDetail.from_payload(event.detail)
    assert detail.snapshot_evidence.source_published_at is None
    assert detail.snapshot_evidence.fact_content_hash == "a" * 64
    assert detail.snapshot_evidence.first_seen_at == record.seal.snapshot.first_seen_at
    assert (
        detail.snapshot_evidence.response_completed_at
        == record.seal.snapshot.raw_reference.response_completed_at
    )
    assert coordinator.transaction_entries == 1
    assert coordinator.write_calls == 1
    assert principal.assertions >= 2


def test_publish_rejects_event_time_before_permission_check_without_writing() -> None:
    coordinator = FakeCoordinator()
    bridge = _bridge(coordinator)
    record = _record(published_at=NOW - timedelta(seconds=2))
    principal = _principal(verified_at=NOW - timedelta(seconds=1))

    with coordinator.outer_transaction(), pytest.raises(CalendarFormalPublicationApplicationError):
        bridge.record_published(record, principal=cast(LockedCalendarPublisherPrincipal, principal))

    assert coordinator.write_calls == 0
    assert coordinator.events == {}


def test_publish_rejects_principal_bound_to_another_database_alias() -> None:
    coordinator = FakeCoordinator()
    bridge = _bridge(coordinator)
    principal = _principal(database_alias="archive")

    with coordinator.outer_transaction(), pytest.raises(CalendarFormalPublicationApplicationError):
        bridge.record_published(
            _record(), principal=cast(LockedCalendarPublisherPrincipal, principal)
        )

    assert coordinator.write_calls == 0
    assert coordinator.events == {}


def test_current_replay_keeps_original_pair_but_requires_same_live_actor() -> None:
    coordinator = FakeCoordinator()
    bridge = _bridge(coordinator)
    record = _record()
    original_principal = _principal(verified_at=record.published_at)
    with coordinator.outer_transaction():
        original = bridge.record_published(
            record, principal=cast(LockedCalendarPublisherPrincipal, original_principal)
        )

    retry = _principal(verified_at=NOW + timedelta(days=1))
    with coordinator.outer_transaction():
        replay = bridge.verify_current_replay(
            record, principal=cast(LockedCalendarPublisherPrincipal, retry)
        )

    assert replay == original
    assert coordinator.write_calls == 1
    assert coordinator.outboxes[replay.event_id].event.recorded_at == record.published_at


def test_integrity_read_needs_no_original_publish_grant_but_joins_same_outer_uow() -> None:
    coordinator = FakeCoordinator()
    bridge = _bridge(coordinator)
    record = _record()
    original_principal = _principal(verified_at=record.published_at)
    with coordinator.outer_transaction():
        original = bridge.record_published(
            record, principal=cast(LockedCalendarPublisherPrincipal, original_principal)
        )

    with coordinator.outer_transaction():
        integrity = bridge.verify_published_integrity(record, as_of=NOW + timedelta(days=1))

    assert integrity == original
    assert coordinator.write_calls == 1
    assert coordinator.list_calls == 0
    assert coordinator.transaction_entries == 2


def test_current_replay_rejects_revoked_publisher_even_when_integrity_read_succeeds() -> None:
    coordinator = FakeCoordinator()
    bridge = _bridge(coordinator)
    record = _record()
    with coordinator.outer_transaction():
        bridge.record_published(
            record,
            principal=cast(
                LockedCalendarPublisherPrincipal, _principal(verified_at=record.published_at)
            ),
        )

    with coordinator.outer_transaction():
        bridge.verify_published_integrity(record, as_of=NOW + timedelta(days=1))
    revoked = _principal(live=False)
    with coordinator.outer_transaction(), pytest.raises(AuthorizationError):
        bridge.verify_current_replay(
            record, principal=cast(LockedCalendarPublisherPrincipal, revoked)
        )

    assert coordinator.write_calls == 1


def test_integrity_read_rejects_wrong_alias_and_future_cutoff() -> None:
    coordinator = FakeCoordinator()
    bridge = _bridge(coordinator)
    record = _record()
    with pytest.raises(CalendarFormalPublicationApplicationError):
        bridge.verify_published_integrity(record, as_of=record.published_at - timedelta(seconds=1))

    with pytest.raises(CalendarPublicationAuditUnavailable):
        CoreCalendarFormalPublicationAuditBridge(
            using="archive",
            coordinator=cast(CalendarPublicationAuditCoordinator, coordinator),
        )
