"""Native PostgreSQL races for the formal exchange-calendar publication lane."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, timedelta
from threading import Barrier, Event, Lock
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import (
    DEFAULT_DB_ALIAS,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone

from apps.audit.application.calendar_publication_audit import (
    CalendarPublicationAuditCorruption,
    CalendarPublicationAuditUnavailable,
)
from apps.audit.infrastructure.system_audit_delivery_receipt import (
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
from apps.audit.infrastructure.system_audit_repository import DjangoSystemAuditEventRepository
from apps.data_center.application.calendar_publication_authority import (
    CalendarPublisherSessionRequestProof,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationRequest,
    CalendarPublicationAuditPair,
    CalendarPublicationTransition,
    PublishExchangeCalendarSnapshotUseCase,
    ReadCurrentExchangeCalendarPublicationQuery,
    ReadCurrentExchangeCalendarPublicationUseCase,
)
from apps.data_center.infrastructure.calendar_publication_authority_repository import (
    DjangoCalendarPublisherAuthorityRepository,
)
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.exchange_calendar_repository import (
    DjangoExchangeCalendarSnapshotRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
)
from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
    DjangoFormalExchangeCalendarPublicationRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from core.exceptions import AuthorizationError, DataFetchError
from core.integration.calendar_formal_publication_audit import (
    CoreCalendarFormalPublicationAuditBridge,
)
from tests.component.data_center.test_formal_exchange_calendar_publication_repository import (
    _DATASET,
    _AuditPort,
    _candidate,
    _Principal,
    _ready,
    _request,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "apps.data_center",
        "apps.audit",
    ],
)

UserModel = get_user_model()
_SCHEMA_MODELS = (
    ContentType,
    Permission,
    Group,
    UserModel,
    Session,
    DatasetContractModel,
    DatasetPublicationPolicyModel,
    RawPayloadModel,
    ExchangeCalendarSnapshotFactModel,
    CanonicalPublicationModel,
    PublicationMemberModel,
    CoverageSnapshotModel,
    CanonicalPublicationPointerModel,
    SystemAuditEventModel,
    SystemAuditOutboxModel,
    SystemAuditDeliveryReceiptModel,
)


@pytest.fixture(autouse=True)
def _postgres_publication_schema(
    django_db_blocker: object,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate only auth, calendar, canonical-publication, and Audit tables."""

    if connection.vendor != "postgresql":
        pytest.skip("formal calendar lock-order tests require native PostgreSQL")
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(_SCHEMA_MODELS):
            try:
                yield
            finally:
                _clear_auth_join_rows()


def _clear_auth_join_rows() -> None:
    """Remove only implicit auth M2M rows that isolated_schema cannot enumerate."""

    through_models = (
        UserModel.user_permissions.through,
        UserModel.groups.through,
        Group.permissions.through,
    )
    for model in through_models:
        model._base_manager.using(DEFAULT_DB_ALIAS).all().delete()


def _set_worker_timeouts() -> None:
    """Bound lock waits so a failed concurrency assertion cannot hang pytest."""

    with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
        cursor.execute("SET statement_timeout = '20000ms'")
        cursor.execute("SET lock_timeout = '15000ms'")


def _backend_pid() -> int:
    """Return the current connection's PostgreSQL backend identity."""

    with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def _wait_for_exact_blocker(waiters: tuple[int, ...], blocker: int) -> int:
    """Return the waiter whose PostgreSQL lock graph names the exact blocker."""

    deadline = monotonic() + 8.0
    while monotonic() < deadline:
        for waiter in waiters:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT wait_event_type, pg_blocking_pids(pid) "
                    "FROM pg_stat_activity WHERE pid = %s",
                    [waiter],
                )
                row = cursor.fetchone()
            if row is not None and row[0] == "Lock" and blocker in row[1]:
                return waiter
            Event().wait(0.02)
    raise AssertionError(f"No PostgreSQL backend in {waiters!r} was blocked by backend {blocker}")


class _BlockingAuditPort(_AuditPort):
    """Hold a successful first publisher after canonical writes but before commit."""

    def __init__(self) -> None:
        super().__init__()
        self.audit_started = Event()
        self.release_audit = Event()
        self.holder_pid: int | None = None

    def record_published(
        self,
        record: object,
        *,
        principal: _Principal,
    ) -> CalendarPublicationAuditPair:
        """Expose the held scope lock while returning the normal test receipt later."""

        pair = super().record_published(record, principal=principal)
        self.holder_pid = _backend_pid()
        self.audit_started.set()
        if not self.release_audit.wait(timeout=12):
            raise AssertionError("test did not release the first publisher's Audit boundary")
        return pair


def _publish_worker(
    *,
    label: str,
    request: CalendarFormalPublicationRequest,
    audit_port: _AuditPort,
    principal: _Principal,
    clock: Any,
    start: Barrier,
    pids: dict[str, int],
    pids_lock: Lock,
) -> tuple[str, str]:
    """Publish one prebuilt CAS request from a dedicated database connection."""

    close_old_connections()
    try:
        _set_worker_timeouts()
        backend_pid = _backend_pid()
        with pids_lock:
            pids[label] = backend_pid
        start.wait(timeout=10)
        repository = DjangoFormalExchangeCalendarPublicationRepository(
            audit_port=audit_port,
            using=DEFAULT_DB_ALIAS,
            clock=clock.now,
        )
        try:
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                commit = repository.publish(request, principal=principal)
        except DataFetchError as error:
            return "blocked", error.code
        return "published", commit.record.publication_id
    finally:
        connections[DEFAULT_DB_ALIAS].close()


def _real_audit_bridge() -> CoreCalendarFormalPublicationAuditBridge:
    """Build the actual Audit event/outbox integration for this alias."""

    return CoreCalendarFormalPublicationAuditBridge(
        using=DEFAULT_DB_ALIAS,
        coordinator=DjangoSystemAuditEventOutboxCoordinator(using=DEFAULT_DB_ALIAS),
    )


def _actual_publisher(username: str) -> tuple[Any, CalendarPublisherSessionRequestProof]:
    """Create one session witness and an explicit persisted calendar permission."""

    user = UserModel.objects.create_user(
        username=username,
        password=None,
        is_active=True,
    )
    content_type, _ = ContentType.objects.get_or_create(
        app_label="data_center",
        model="exchangecalendarsnapshotfactmodel",
    )
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename="publish_exchange_calendar",
        defaults={"name": "Test-only calendar publication permission"},
    )
    assert permission.content_type_id == content_type.pk
    user.user_permissions.add(permission)

    authenticated_at = timezone.now().astimezone(UTC)
    session_key = uuid4().hex
    Session.objects.create(
        session_key=session_key,
        session_data=SessionStore().encode(
            {
                "_auth_user_id": str(user.pk),
                "_auth_user_backend": settings.AUTHENTICATION_BACKENDS[0],
                "_auth_user_hash": user.get_session_auth_hash(),
            }
        ),
        expire_date=authenticated_at + timedelta(minutes=10),
    )
    return user, CalendarPublisherSessionRequestProof(
        user_id=int(user.pk),
        session_key=session_key,
        request_authenticated_at=authenticated_at,
        request_user_database_alias=DEFAULT_DB_ALIAS,
        database_alias=DEFAULT_DB_ALIAS,
    )


def _authorized_publish(
    *,
    authority: DjangoCalendarPublisherAuthorityRepository,
    use_case: PublishExchangeCalendarSnapshotUseCase,
    proof: CalendarPublisherSessionRequestProof,
    request: CalendarFormalPublicationRequest,
) -> Any:
    """Run the use case only while the real Session and grant rows are locked."""

    with authority.locked_calendar_publisher(proof) as principal:
        return use_case.execute(request, principal=principal)


def _counts() -> tuple[int, int, int, int]:
    """Return publication, pointer, event, and outbox row counts."""

    return (
        CanonicalPublicationModel._default_manager.count(),
        CanonicalPublicationPointerModel._default_manager.count(),
        SystemAuditEventModel._default_manager.count(),
        SystemAuditOutboxModel._default_manager.count(),
    )


def test_postgres_first_publication_cas_waits_on_exact_scope_winner() -> None:
    """A second absent-pointer writer waits for and then loses to the exact winner."""

    _snapshot, _audit, clock, principal, request = _ready()
    audit_port = _BlockingAuditPort()
    start = Barrier(3, timeout=10)
    pids: dict[str, int] = {}
    pids_lock = Lock()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first: Future[tuple[str, str]] = pool.submit(
            _publish_worker,
            label="first",
            request=request,
            audit_port=audit_port,
            principal=principal,
            clock=clock,
            start=start,
            pids=pids,
            pids_lock=pids_lock,
        )
        second: Future[tuple[str, str]] = pool.submit(
            _publish_worker,
            label="second",
            request=request,
            audit_port=audit_port,
            principal=principal,
            clock=clock,
            start=start,
            pids=pids,
            pids_lock=pids_lock,
        )
        start.wait(timeout=10)
        try:
            assert audit_port.audit_started.wait(timeout=10)
            assert audit_port.holder_pid is not None
            waiter_pid = _wait_for_exact_blocker(
                tuple(pids.values()),
                audit_port.holder_pid,
            )
            assert waiter_pid in pids.values()
        finally:
            audit_port.release_audit.set()
        outcomes = (first.result(timeout=15), second.result(timeout=15))

    assert sorted(outcome[0] for outcome in outcomes) == ["blocked", "published"]
    assert next(code for kind, code in outcomes if kind == "blocked") == (
        "CALENDAR_POINTER_CAS_MISMATCH"
    )
    assert CanonicalPublicationModel._default_manager.count() == 1
    assert CanonicalPublicationPointerModel._default_manager.count() == 1
    pointer = CanonicalPublicationPointerModel._default_manager.get()
    publication = CanonicalPublicationModel._default_manager.get()
    assert pointer.publication_id == publication.publication_id
    assert pointer.updated_at == publication.published_at
    assert len(audit_port.pairs) == 1


def test_postgres_forward_cas_race_keeps_pointer_row_and_supersedes_once() -> None:
    """Two forwards from one old epoch yield one winner on the same pointer row."""

    first_snapshot, audit_port, clock, principal, first_request = _ready()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit_port,
        using=DEFAULT_DB_ALIAS,
        clock=clock.now,
    )
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        first = repository.publish(first_request, principal=principal)

    contract = DatasetContractModel._default_manager.get(dataset_key=_DATASET.value)
    policy = DatasetPublicationPolicyModel._default_manager.get(dataset_key=_DATASET.value)
    left_snapshot = DjangoExchangeCalendarSnapshotRepository().save(_candidate())
    right_snapshot = DjangoExchangeCalendarSnapshotRepository().save(_candidate())
    clock.value = first.record.published_at + timedelta(seconds=1)
    left_request = _request(
        left_snapshot,
        contract,
        policy,
        expected_pointer=first.pointer,
        activation_id="forward-race-left",
    )
    right_request = _request(
        right_snapshot,
        contract,
        policy,
        expected_pointer=first.pointer,
        activation_id="forward-race-right",
    )

    start = Barrier(3, timeout=10)
    pids: dict[str, int] = {}
    pids_lock = Lock()
    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(
            _publish_worker,
            label="left",
            request=left_request,
            audit_port=audit_port,
            principal=principal,
            clock=clock,
            start=start,
            pids=pids,
            pids_lock=pids_lock,
        )
        right = pool.submit(
            _publish_worker,
            label="right",
            request=right_request,
            audit_port=audit_port,
            principal=principal,
            clock=clock,
            start=start,
            pids=pids,
            pids_lock=pids_lock,
        )
        start.wait(timeout=10)
        outcomes = (left.result(timeout=20), right.result(timeout=20))

    assert sorted(outcome[0] for outcome in outcomes) == ["blocked", "published"]
    assert next(code for kind, code in outcomes if kind == "blocked") == (
        "CALENDAR_POINTER_CAS_MISMATCH"
    )
    pointer = CanonicalPublicationPointerModel._default_manager.get()
    assert str(pointer.pointer_id) == first.pointer.pointer_id
    assert pointer.updated_at > first.pointer.updated_at
    assert CanonicalPublicationModel._default_manager.count() == 2
    assert CanonicalPublicationModel._default_manager.filter(state="published").count() == 1
    old_record = CanonicalPublicationModel._default_manager.get(
        publication_id=UUID(first.record.publication_id)
    )
    assert old_record.state == "superseded"
    assert old_record.superseded_at == pointer.updated_at
    current_record = CanonicalPublicationModel._default_manager.get(
        publication_id=pointer.publication_id
    )
    assert current_record.published_at == pointer.updated_at
    assert first_snapshot.snapshot_id != left_snapshot.snapshot_id


def test_postgres_catalog_row_lock_before_share_allows_repo_publish() -> None:
    """The real publication path does not row-lock catalog before its SHARE fence."""

    _snapshot, _audit, clock, principal, request = _ready()
    completed = Event()
    worker_result: dict[str, tuple[str, str]] = {}
    start = Barrier(2, timeout=10)
    pids: dict[str, int] = {}
    pids_lock = Lock()

    def publish() -> None:
        try:
            worker_result["result"] = _publish_worker(
                label="repo-publisher",
                request=request,
                audit_port=_AuditPort(),
                principal=principal,
                clock=clock,
                start=start,
                pids=pids,
                pids_lock=pids_lock,
            )
        finally:
            completed.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            contract = (
                DatasetContractModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .get(dataset_key=_DATASET.value)
            )
            future = pool.submit(publish)
            start.wait(timeout=10)
            completed_before_release = completed.wait(timeout=5)
            if completed_before_release:
                assert worker_result["result"][0] == "published"
            contract.owner = "writer-after-share"
            contract.save(using=DEFAULT_DB_ALIAS, update_fields=("owner",))
        future.result(timeout=15)
        result = worker_result["result"]

    assert completed_before_release, "repository waited on a catalog row lock before SHARE"
    assert result[0] == "published"
    pointer = CanonicalPublicationPointerModel._default_manager.get()
    assert result[1] == str(pointer.publication_id)
    assert DatasetContractModel._default_manager.get(dataset_key=_DATASET.value).owner == (
        "writer-after-share"
    )


def test_postgres_catalog_dml_before_share_repo_reads_committed_inactive_state() -> None:
    """The repository waits for catalog DML then blocks on the committed state."""

    _snapshot, _audit, clock, principal, request = _ready()
    start = Barrier(2, timeout=10)
    pids: dict[str, int] = {}
    pids_lock = Lock()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            contract = DatasetContractModel._default_manager.get(dataset_key=_DATASET.value)
            contract.active = False
            contract.save(using=DEFAULT_DB_ALIAS, update_fields=("active",))
            blocker_pid = _backend_pid()
            future = pool.submit(
                _publish_worker,
                label="repo-publisher",
                request=request,
                audit_port=_AuditPort(),
                principal=principal,
                clock=clock,
                start=start,
                pids=pids,
                pids_lock=pids_lock,
            )
            start.wait(timeout=10)
            assert "repo-publisher" in pids
            assert (
                _wait_for_exact_blocker((pids["repo-publisher"],), blocker_pid)
                == pids["repo-publisher"]
            )
        assert future.result(timeout=15) == (
            "blocked",
            "CALENDAR_FORMAL_CONTRACT_MISSING",
        )

    assert CanonicalPublicationModel._default_manager.count() == 0
    assert CanonicalPublicationPointerModel._default_manager.count() == 0


@pytest.mark.parametrize("failure_stage", ["event", "outbox"])
def test_real_audit_failure_after_pointer_write_rolls_back_publication(
    failure_stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real Audit append or enqueue failure rolls back canonical state in the same UOW."""

    _snapshot, _fake_audit, _clock, _fake_principal, request = _ready()
    _user, proof = _actual_publisher(f"calendar-audit-failure-{failure_stage}")
    authority = DjangoCalendarPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)
    audit_port = _real_audit_bridge()
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit_port,
        using=DEFAULT_DB_ALIAS,
    )
    use_case = PublishExchangeCalendarSnapshotUseCase(repository)

    def assert_pointer_was_written() -> None:
        publication = CanonicalPublicationModel._default_manager.get(state="published")
        pointer = CanonicalPublicationPointerModel._default_manager.get()
        assert pointer.publication_id == publication.publication_id
        assert pointer.updated_at == publication.published_at

    if failure_stage == "event":

        def fail_event_append(*_args: object, **_kwargs: object) -> None:
            assert_pointer_was_written()
            raise RuntimeError("injected PostgreSQL calendar event append failure")

        monkeypatch.setattr(
            DjangoSystemAuditEventRepository,
            "append_calendar_targeted",
            fail_event_append,
        )
    else:

        def fail_outbox_enqueue(*_args: object, **_kwargs: object) -> None:
            assert_pointer_was_written()
            assert SystemAuditEventModel._default_manager.count() == 1
            raise RuntimeError("injected PostgreSQL calendar outbox enqueue failure")

        monkeypatch.setattr(
            DjangoSystemAuditOutboxRepository,
            "enqueue_targeted",
            fail_outbox_enqueue,
        )

    with pytest.raises(CalendarPublicationAuditUnavailable):
        _authorized_publish(
            authority=authority,
            use_case=use_case,
            proof=proof,
            request=request,
        )

    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CoverageSnapshotModel._default_manager.count() == 0
    assert CanonicalPublicationPointerModel._default_manager.count() == 0
    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0


def test_real_session_publish_replay_read_after_revocation_and_replay_denial() -> None:
    """Current reference reads survive publisher revocation; replay still needs it."""

    snapshot, _fake_audit, _clock, _fake_principal, request = _ready()
    user, proof = _actual_publisher("calendar-authorized-publisher")
    authority = DjangoCalendarPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=_real_audit_bridge(),
        using=DEFAULT_DB_ALIAS,
    )
    publish = PublishExchangeCalendarSnapshotUseCase(repository)
    first = _authorized_publish(
        authority=authority,
        use_case=publish,
        proof=proof,
        request=request,
    )
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1

    replay_request = _request(
        snapshot,
        DatasetContractModel._default_manager.get(dataset_key=_DATASET.value),
        DatasetPublicationPolicyModel._default_manager.get(dataset_key=_DATASET.value),
        expected_pointer=first.pointer,
        activation_id=request.activation_id,
    )
    replay = _authorized_publish(
        authority=authority,
        use_case=publish,
        proof=proof,
        request=replay_request,
    )
    assert replay.transition is CalendarPublicationTransition.EXACT_CURRENT_REPLAY
    assert replay.record.publication_id == first.record.publication_id
    assert replay.pointer == first.pointer
    assert _counts() == (1, 1, 1, 1)

    successor = DjangoExchangeCalendarSnapshotRepository().save(_candidate())
    forward_request = _request(
        successor,
        DatasetContractModel._default_manager.get(dataset_key=_DATASET.value),
        DatasetPublicationPolicyModel._default_manager.get(dataset_key=_DATASET.value),
        expected_pointer=first.pointer,
        activation_id="real-session-forward-publication",
    )
    forward = _authorized_publish(
        authority=authority,
        use_case=publish,
        proof=proof,
        request=forward_request,
    )
    assert forward.transition is CalendarPublicationTransition.FORWARD_PUBLISH
    assert forward.pointer.pointer_id == first.pointer.pointer_id
    assert forward.record.publication_id != first.record.publication_id
    assert forward.record.published_at > first.record.published_at
    previous = CanonicalPublicationModel._default_manager.get(
        publication_id=UUID(first.record.publication_id)
    )
    assert previous.state == "superseded"
    assert previous.superseded_at == forward.record.published_at
    assert _counts() == (2, 1, 2, 2)
    assert PublicationMemberModel._default_manager.count() == 2
    assert CoverageSnapshotModel._default_manager.count() == 2
    assert SystemAuditEventModel._default_manager.count() == 2
    assert SystemAuditOutboxModel._default_manager.count() == 2
    replay_request = _request(
        successor,
        DatasetContractModel._default_manager.get(dataset_key=_DATASET.value),
        DatasetPublicationPolicyModel._default_manager.get(dataset_key=_DATASET.value),
        expected_pointer=forward.pointer,
        activation_id=forward_request.activation_id,
    )
    successor_replay = _authorized_publish(
        authority=authority,
        use_case=publish,
        proof=proof,
        request=replay_request,
    )
    assert successor_replay.transition is CalendarPublicationTransition.EXACT_CURRENT_REPLAY
    assert successor_replay.record == forward.record
    assert successor_replay.pointer == forward.pointer
    assert _counts() == (2, 1, 2, 2)
    assert SystemAuditEventModel._default_manager.count() == 2
    assert SystemAuditOutboxModel._default_manager.count() == 2

    reader = ReadCurrentExchangeCalendarPublicationUseCase(repository)
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        result = reader.execute(
            ReadCurrentExchangeCalendarPublicationQuery(
                dataset_key=_DATASET.value,
                exchange="SSE",
                as_of=timezone.now().astimezone(UTC),
            )
        )
    assert result.record.publication_id == forward.record.publication_id
    assert result.must_not_execute is True

    user.user_permissions.clear()
    before = _counts()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        after_revocation = reader.execute(
            ReadCurrentExchangeCalendarPublicationQuery(
                dataset_key=_DATASET.value,
                exchange="SSE",
                as_of=timezone.now().astimezone(UTC),
            )
        )
    assert after_revocation.record == result.record
    assert after_revocation.pointer == result.pointer
    assert after_revocation.must_not_execute is True
    assert _counts() == before
    with pytest.raises(AuthorizationError):
        _authorized_publish(
            authority=authority,
            use_case=publish,
            proof=proof,
            request=replay_request,
        )
    assert _counts() == before
    assert CanonicalPublicationPointerModel._default_manager.get().publication_id == UUID(
        forward.record.publication_id
    )


@pytest.mark.parametrize("missing_half", ["event", "outbox"])
@pytest.mark.parametrize("operation", ["replay", "forward"])
def test_real_audit_missing_half_blocks_replay_and_forward_without_repair(
    missing_half: str,
    operation: str,
) -> None:
    """A corrupt old Audit pair blocks both transitions without moving the pointer."""

    snapshot, _fake_audit, _clock, _fake_principal, request = _ready()
    _user, proof = _actual_publisher(f"calendar-half-pair-{missing_half}-{operation}")
    authority = DjangoCalendarPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=_real_audit_bridge(),
        using=DEFAULT_DB_ALIAS,
    )
    publish = PublishExchangeCalendarSnapshotUseCase(repository)
    first = _authorized_publish(
        authority=authority,
        use_case=publish,
        proof=proof,
        request=request,
    )
    event = SystemAuditEventModel._default_manager.get(publication_id=first.record.publication_id)
    outbox = SystemAuditOutboxModel._default_manager.get(event_id=event.event_id)
    if missing_half == "event":
        with connection.cursor() as cursor:
            table = connection.ops.quote_name(SystemAuditEventModel._meta.db_table)
            cursor.execute(f"DELETE FROM {table} WHERE id = %s", [event.pk])
    else:
        with connection.cursor() as cursor:
            table = connection.ops.quote_name(SystemAuditOutboxModel._meta.db_table)
            cursor.execute(f"DELETE FROM {table} WHERE outbox_id = %s", [str(outbox.outbox_id)])

    target_snapshot = (
        snapshot
        if operation == "replay"
        else DjangoExchangeCalendarSnapshotRepository().save(_candidate())
    )
    transition_request = _request(
        target_snapshot,
        DatasetContractModel._default_manager.get(dataset_key=_DATASET.value),
        DatasetPublicationPolicyModel._default_manager.get(dataset_key=_DATASET.value),
        expected_pointer=first.pointer,
        activation_id=(
            request.activation_id if operation == "replay" else "forward-after-corruption"
        ),
    )
    before = _counts()
    with pytest.raises(CalendarPublicationAuditCorruption):
        _authorized_publish(
            authority=authority,
            use_case=publish,
            proof=proof,
            request=transition_request,
        )
    assert _counts() == before
    assert CanonicalPublicationPointerModel._default_manager.get().publication_id == UUID(
        first.record.publication_id
    )
