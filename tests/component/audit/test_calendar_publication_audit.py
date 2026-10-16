from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_system_event")

import django

django.setup()

import pytest
from django.apps import apps
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.application.calendar_publication_audit import (
    AppendCalendarPublicationAuditUseCase,
    CalendarPublicationAuditCorruption,
    CalendarPublicationAuditReaderContext,
    CalendarPublicationAuditUnavailable,
    CalendarPublicationBlockedObservation,
    CalendarPublicationPublishedObservation,
    ListCalendarPublicationAuditEventsCommand,
    ListCalendarPublicationAuditEventsUseCase,
    build_calendar_publication_published_event,
)
from apps.audit.application.system_audit_composition import system_audit_authority_content_hash
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.application.system_audit_outbox_dispatcher import (
    DispatchSystemAuditOutboxCommand,
    DispatchSystemAuditOutboxUseCase,
)
from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.audit.domain.calendar_publication_audit import (
    CalendarPublicationAuditEvidence,
    CalendarPublicationBlockedDetail,
    CalendarPublicationPublishedDetail,
    calendar_publication_stream_id,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.audit.infrastructure.system_audit_delivery_receipt import (
    DjangoSystemAuditDeliveryReceiptPublisher,
    SystemAuditDeliveryReceiptModel,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
)
from apps.audit.infrastructure.system_audit_outbox_unit_of_work import (
    DjangoSystemAuditOutboxUnitOfWork,
)
from apps.audit.infrastructure.system_audit_repository import (
    DjangoSystemAuditEventRepository,
    SystemAuditConflict,
    SystemAuditCorruption,
)
from core.exceptions import AuthorizationError
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[apps.get_app_config("audit").name],
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
DATASET = "exchange.calendar.days"
EXCHANGE = "SSE"


@dataclass
class FakePublisherPrincipal:
    """Lock-lease-shaped principal for the injected test composition."""

    actor_type: str = "django_user"
    actor_id: str = "django-user:7"
    permission_codename: str = "publish_exchange_calendar"
    database_alias: str = "default"
    verified_at: datetime = NOW - timedelta(seconds=1)
    user_id: int = 7
    live: bool = True

    def assert_live(self) -> None:
        """Reject writes after this test's simulated permission lease expires."""

        if not self.live:
            raise AuthorizationError("test publisher lease expired")


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Create and clear only the event, outbox, and durable receipt tables."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(
            (
                SystemAuditEventModel,
                SystemAuditOutboxModel,
                SystemAuditDeliveryReceiptModel,
            )
        ):
            yield


def _evidence(
    *, dataset_key: str = DATASET, exchange: str = EXCHANGE
) -> CalendarPublicationAuditEvidence:
    """Build an immutable snapshot/raw binding with separate hash domains."""

    first_seen = NOW - timedelta(hours=2)
    return CalendarPublicationAuditEvidence(
        snapshot_id=str(uuid4()),
        exchange=exchange,
        coverage_start=date(2026, 10, 16),
        coverage_end=date(2026, 12, 31),
        provider_name="tushare",
        first_seen_at=first_seen,
        snapshot_recorded_at=first_seen + timedelta(seconds=1),
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
        response_completed_at=first_seen,
        raw_provider_name="tushare",
        raw_dataset_key=dataset_key,
        raw_transport="http-json",
    )


def _published_observation(
    *,
    dataset_key: str = DATASET,
    exchange: str = EXCHANGE,
    publication_id: str = "publication-001",
    recorded_at: datetime = NOW,
) -> CalendarPublicationPublishedObservation:
    """Build one complete publication event observation for the real writer."""

    return CalendarPublicationPublishedObservation(
        detail=CalendarPublicationPublishedDetail(
            dataset_key=dataset_key,
            exchange=exchange,
            publication_id=publication_id,
            publication_key="effective",
            policy_version="calendar-v1",
            publication_hash="3" * 64,
            snapshot_evidence=_evidence(dataset_key=dataset_key, exchange=exchange),
        ),
        recorded_at=recorded_at,
    )


def _append_published(
    coordinator: DjangoSystemAuditEventOutboxCoordinator,
    observation: CalendarPublicationPublishedObservation,
    *,
    principal: FakePublisherPrincipal | None = None,
    exact_replay: bool = False,
) -> SystemAuditEventOutboxCommit:
    """Append one real event/outbox pair inside a publisher-owned transaction."""

    with transaction.atomic(using="default"):
        return AppendCalendarPublicationAuditUseCase(
            coordinator
        ).execute_published_in_caller_transaction(
            observation,
            principal=principal or FakePublisherPrincipal(),
            exact_replay=exact_replay,
        )


def _append_blocked(
    coordinator: DjangoSystemAuditEventOutboxCoordinator,
    *,
    request_id: str,
    recorded_at: datetime,
) -> SystemAuditEventOutboxCommit:
    """Append one blocked attempt under the same exact calendar stream."""

    observation = CalendarPublicationBlockedObservation(
        detail=CalendarPublicationBlockedDetail(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            request_id=request_id,
            blocked_reason="calendar_source_unavailable",
        ),
        recorded_at=recorded_at,
    )
    with transaction.atomic(using="default"):
        return AppendCalendarPublicationAuditUseCase(
            coordinator
        ).execute_blocked_in_caller_transaction(
            observation,
            principal=FakePublisherPrincipal(),
            exact_replay=False,
        )


def _build_unscoped_event() -> SystemAuditEvent:
    """Return a valid no-scope event for checking the unchanged generic guard."""

    observation = _published_observation()
    return build_calendar_publication_published_event(
        observation,
        principal=FakePublisherPrincipal(),
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )


def test_calendar_append_is_exact_pair_and_generic_null_scope_stays_closed() -> None:
    event_repository = DjangoSystemAuditEventRepository()
    event = _build_unscoped_event()
    with event_repository.atomic():
        with pytest.raises(SystemAuditConflict, match="explicit scope"):
            event_repository.append(
                event,
                expected_predecessor_hash=None,
                recorded_at=NOW,
            )

    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    first = _append_published(coordinator, _published_observation())
    assert first.event.scope is None
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1
    outbox = SystemAuditOutboxModel._default_manager.get()
    assert outbox.event_id == first.event.event_id
    assert outbox.payload_hash == first.event.content_hash


def test_calendar_exact_replay_returns_original_pair_and_missing_outbox_fails_closed() -> None:
    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    observation = _published_observation()
    first = _append_published(coordinator, observation)
    replay = _append_published(coordinator, observation, exact_replay=True)

    assert replay == first
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1

    with connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {connection.ops.quote_name(SystemAuditOutboxModel._meta.db_table)}"
        )

    with pytest.raises(CalendarPublicationAuditCorruption, match="no exact outbox"):
        _append_published(coordinator, observation, exact_replay=True)
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 0


def test_calendar_orphan_outbox_cannot_be_adopted_as_a_new_event() -> None:
    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    observation = _published_observation()
    _append_published(coordinator, observation)

    with connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {connection.ops.quote_name(SystemAuditEventModel._meta.db_table)}"
        )

    with pytest.raises(CalendarPublicationAuditCorruption, match="outbox exists without"):
        _append_published(coordinator, observation)
    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 1


def test_outbox_failure_rolls_back_calendar_event_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = DjangoSystemAuditEventOutboxCoordinator()

    def fail_enqueue_targeted(
        _repository: DjangoSystemAuditOutboxRepository,
        _event: SystemAuditEvent,
        *,
        available_at: datetime,
        created_at: datetime,
    ) -> object:
        del available_at, created_at
        raise RuntimeError("simulated calendar outbox failure")

    monkeypatch.setattr(
        DjangoSystemAuditOutboxRepository,
        "enqueue_targeted",
        fail_enqueue_targeted,
    )
    with pytest.raises(
        CalendarPublicationAuditUnavailable,
        match="calendar Audit event/outbox append failed",
    ):
        _append_published(coordinator, _published_observation())

    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0


class FakeCalendarAuditReaderAuthority:
    """Test-only locked permission provider for one exact calendar reader."""

    @dataclass
    class Principal:
        actor_type: str = "django_user"
        actor_id: str = "django-user:7"
        permission_codename: str = "view_exchange_calendar_publication_audit"
        database_alias: str = "default"
        authority_content_hash: str = "sha256:" + "9" * 64
        verified_at: datetime = NOW
        session_expires_at: datetime = NOW + timedelta(hours=1)
        user_id: int = 7

        def assert_live(self) -> None:
            """Keep the test lease live for the entire synchronous read."""

    @contextmanager
    def _locked_context(
        self, context: CalendarPublicationAuditReaderContext
    ) -> Iterator[CalendarPublicationAuditReaderContext]:
        context.assert_live()
        try:
            yield context
        except BaseException:
            raise
        else:
            context.assert_live()

    def lock_reader(
        self,
        *,
        request_proof: object,
        dataset_key: str,
        exchange: str,
        database_alias: str,
    ) -> AbstractContextManager[CalendarPublicationAuditReaderContext] | None:
        """Return a lock-shaped test lease matching the requested selector."""

        del request_proof
        if dataset_key != DATASET or exchange != EXCHANGE or database_alias != "default":
            return None
        context = CalendarPublicationAuditReaderContext._from_authority(
            principal=self.Principal(),
            dataset_key=dataset_key,
            exchange=exchange,
        )
        return self._locked_context(context)


def test_calendar_reader_uses_exact_dataset_exchange_and_pit_selector() -> None:
    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    first = _published_observation(recorded_at=NOW)
    second = _published_observation(
        publication_id="publication-002",
        recorded_at=NOW + timedelta(minutes=2),
    )
    _append_published(coordinator, first)
    _append_published(coordinator, second)

    result = ListCalendarPublicationAuditEventsUseCase(
        authority_provider=FakeCalendarAuditReaderAuthority(),
        repository=coordinator,
    ).execute(
        ListCalendarPublicationAuditEventsCommand(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            as_of=NOW + timedelta(minutes=1),
            request_proof=object(),
        )
    )

    assert len(result.events) == 1
    assert result.events[0].publication_id == "publication-001"
    assert result.events[0].stream_id == calendar_publication_stream_id(DATASET, EXCHANGE)
    assert (
        coordinator.list_calendar_publication_events(
            dataset_key=DATASET,
            exchange="SZE",
            as_of=NOW + timedelta(minutes=3),
        )
        == ()
    )


def test_calendar_blocked_event_uses_same_exact_stream_and_chain() -> None:
    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    published = _append_published(coordinator, _published_observation())
    blocked = _append_blocked(
        coordinator,
        request_id="request-blocked-1",
        recorded_at=NOW + timedelta(minutes=1),
    )

    assert blocked.event.sequence_no == published.event.sequence_no + 1
    assert blocked.event.predecessor_hash == published.event.content_hash
    events = coordinator.list_calendar_publication_events(
        dataset_key=DATASET,
        exchange=EXCHANGE,
        as_of=NOW + timedelta(minutes=2),
    )
    assert len(events) == 2
    assert events[1].outcome.value == "blocked"
    assert SystemAuditOutboxModel._default_manager.count() == 2


def test_calendar_exact_selector_ignores_unrelated_corrupt_event() -> None:
    """An unrelated damaged Audit row must not block an exact calendar read."""

    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    target = _append_published(coordinator, _published_observation())
    unrelated = _append_published(
        coordinator,
        _published_observation(
            dataset_key="exchange.calendar.unrelated",
            publication_id="publication-unrelated",
        ),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {connection.ops.quote_name(SystemAuditEventModel._meta.db_table)} "
            "SET canonical_payload = %s WHERE event_id = %s",
            ["{}", unrelated.event.event_id],
        )

    events = coordinator.list_calendar_publication_events(
        dataset_key=DATASET,
        exchange=EXCHANGE,
        as_of=NOW + timedelta(minutes=1),
    )

    assert events == (target.event,)


@pytest.mark.parametrize(
    ("column", "replacement"),
    (
        ("stream_id", "calendar.wrong-stream"),
        ("event_type", "unregistered.calendar.event"),
        ("content_hash", "0" * 64),
    ),
)
def test_calendar_exact_selector_rejects_corruption_in_target_rows(
    column: str,
    replacement: str,
) -> None:
    """The exact query still restores and rejects a damaged target row."""

    event = _append_published(
        DjangoSystemAuditEventOutboxCoordinator(), _published_observation()
    ).event
    allowed_columns = {"stream_id", "event_type", "content_hash"}
    assert column in allowed_columns
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {connection.ops.quote_name(SystemAuditEventModel._meta.db_table)} "
            f"SET {column} = %s WHERE event_id = %s",
            [replacement, event.event_id],
        )

    with pytest.raises(SystemAuditCorruption):
        DjangoSystemAuditEventOutboxCoordinator().list_calendar_publication_events(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            as_of=NOW + timedelta(minutes=1),
        )


def test_calendar_exact_selector_rejects_a_gap_in_the_target_stream() -> None:
    """The narrow ORM query still validates a contiguous predecessor chain."""

    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    first = _append_published(coordinator, _published_observation())
    second = _append_published(
        coordinator,
        _published_observation(
            publication_id="publication-second",
            recorded_at=NOW + timedelta(minutes=1),
        ),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {connection.ops.quote_name(SystemAuditEventModel._meta.db_table)} "
            "WHERE event_id = %s",
            [first.event.event_id],
        )

    with pytest.raises(SystemAuditCorruption, match="sequence gap or fork"):
        coordinator.list_calendar_publication_events(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            as_of=NOW + timedelta(minutes=2),
        )
    assert second.event.sequence_no == 2


def test_calendar_exact_selector_does_not_hide_future_clock_damage_in_target_row() -> None:
    """A corrupted target timestamp cannot make its row disappear at an older PIT."""

    event = _append_published(
        DjangoSystemAuditEventOutboxCoordinator(), _published_observation()
    ).event
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {connection.ops.quote_name(SystemAuditEventModel._meta.db_table)} "
            "SET recorded_at = %s WHERE event_id = %s",
            [NOW + timedelta(hours=1), event.event_id],
        )

    with pytest.raises(SystemAuditCorruption):
        DjangoSystemAuditEventOutboxCoordinator().list_calendar_publication_events(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            as_of=NOW + timedelta(minutes=1),
        )


def test_calendar_scope_none_event_dispatches_to_exact_durable_receipt() -> None:
    """The existing dispatcher preserves a Calendar event in its durable sink."""

    dispatch_at = timezone.now()
    event_commit = _append_published(
        DjangoSystemAuditEventOutboxCoordinator(),
        _published_observation(recorded_at=dispatch_at),
    )
    repository = DjangoSystemAuditOutboxRepository(clock=_FixedOutboxClock(dispatch_at))
    publisher = DjangoSystemAuditDeliveryReceiptPublisher(clock=_FixedOutboxClock(dispatch_at))
    authority = _dispatch_authority(dispatch_at)

    def authority_preflight(*, as_of: datetime) -> SystemAuditReaderContext:
        assert as_of == dispatch_at
        return authority

    result = DispatchSystemAuditOutboxUseCase(
        repository,
        publisher,
        DjangoSystemAuditOutboxUnitOfWork(repository),
        authority_preflight=authority_preflight,
    ).execute(
        DispatchSystemAuditOutboxCommand(
            worker_id="calendar-audit-component",
            as_of=dispatch_at,
            limit=10,
        )
    )

    outbox = SystemAuditOutboxModel._default_manager.get(event_id=event_commit.event.event_id)
    receipt = SystemAuditDeliveryReceiptModel.objects.get(
        event_id=event_commit.event.event_id,
        event_version=event_commit.event.event_version,
    )
    assert result.claimed == result.delivered == 1
    assert result.failed == 0
    assert outbox.status == SystemAuditOutboxModel.STATUS_DELIVERED
    assert event_commit.event.scope is None
    assert receipt.canonical_payload == event_commit.event.to_payload()
    assert receipt.content_hash == event_commit.event.content_hash
    assert receipt.sink_id == DjangoSystemAuditDeliveryReceiptPublisher.SINK_ID


class _FixedOutboxClock:
    """One deterministic server clock for the dispatcher and its durable sink."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _dispatch_authority(as_of: datetime) -> SystemAuditReaderContext:
    """Build a test-only live staff scope accepted by dispatcher preflight."""

    recorded_at = as_of - timedelta(minutes=1)
    valid_until = as_of + timedelta(hours=1)
    source_id = "audit-authority-bundle:calendar-test"
    source_version = "v1-calendar-test"
    actor_id = "django-user:7"
    tenant_id = "tenant:calendar-test"
    owner_id = "owner:audit-test"
    role = "audit_reader"
    authority_state = "active"
    content_hash = system_audit_authority_content_hash(
        source_id=source_id,
        source_version=source_version,
        actor_id=actor_id,
        user_id=7,
        tenant_id=tenant_id,
        owner_id=owner_id,
        is_authenticated=True,
        is_staff=True,
        role=role,
        authority_state=authority_state,
        recorded_at=recorded_at,
        valid_until=valid_until,
    )
    return SystemAuditReaderContext._from_authority(
        authority_source_id=source_id,
        authority_source_version=source_version,
        actor_id=actor_id,
        user_id=7,
        tenant_id=tenant_id,
        owner_id=owner_id,
        authority_content_hash=content_hash,
        is_authenticated=True,
        is_staff=True,
        role=role,
        authority_state=authority_state,
        authority_recorded_at=recorded_at,
        authority_valid_until=valid_until,
    )
