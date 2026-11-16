"""Unexecuted native PostgreSQL contract tests for the isolated C2 candidate.

Copy into ``tests/component/data_center`` only after Root adopts the candidate,
adds migration 0117, and integrates the statutory-source alias/clock patches.
The route below is test-only: the candidate request composition is not yet
mounted on a production URL or management command.
"""

from __future__ import annotations

import threading
import time as time_module
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import DEFAULT_DB_ALIAS, connection, connections, transaction
from django.http import HttpRequest, JsonResponse
from django.test import Client, override_settings
from django.urls import path
from django.utils import timezone

from apps.data_center.application.financial_availability_current import (
    ResolveCurrentFinancialAvailabilityGovernanceQuery,
    resolve_current_financial_availability_governance,
)
from apps.data_center.application.financial_availability_governance import (
    append_and_apply_financial_availability_governance,
    read_financial_availability_governance,
)
from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySessionRequestProof,
    GetFinancialAvailabilityGovernanceQuery,
)
from apps.data_center.application.statutory_source_documents import (
    RetainStatutorySourceDocumentUseCase,
)
from apps.data_center.domain.financial_availability_governance import (
    FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME,
    ExchangeSessionOpeningRuleProposal,
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventIdentity,
    FinancialAvailabilityRecordKind,
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningPhase,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialDisclosureAvailabilityPolicy,
)
from apps.data_center.domain.statutory_source_documents import (
    RetainedStatutorySourceDocumentCapture,
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentRevision,
)
from apps.data_center.financial_availability_e1_composition import (
    apply_financial_availability_governance_from_request,
    revoke_financial_availability_governance_from_request,
)
from apps.data_center.infrastructure.financial_availability_governance_authority import (
    DjangoFinancialAvailabilityPermissionAuthorizer,
)
from apps.data_center.infrastructure.financial_availability_governance_models import (
    FinancialAvailabilityGovernanceRecordModel,
)
from apps.data_center.infrastructure.financial_availability_governance_writer import (
    DjangoFinancialAvailabilityGovernanceRepository,
    DjangoFinancialAvailabilityOwnerEventRepository,
)
from apps.data_center.infrastructure.financial_availability_source_reader import (
    DjangoFinancialAvailabilitySourceReader,
)
from apps.data_center.infrastructure.statutory_source_body_store import (
    StatutorySourceBodyStore,
)
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)
from core.exceptions import AuthenticationError, AuthorizationError, DataValidationError
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.data_center",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
    ],
)

_TEST_BODY = b"synthetic C2 mechanics only; not an official source"
_URL_PATH = "/_test/c2/"
_OPERATIONS: dict[str, _Operation] = {}


@dataclass(slots=True)
class _Operation:
    """Server-side test operation data; request bodies select no actor facts."""

    action: str
    record: FinancialAvailabilityGovernanceRecord
    services: _Services
    source_known_at: datetime | None = None
    apply_event: FinancialAvailabilityOwnerEventIdentity | None = None
    proof: FinancialAvailabilitySessionRequestProof | None = None
    persisted_record: FinancialAvailabilityGovernanceRecord | None = None
    event: FinancialAvailabilityOwnerEventIdentity | None = None


@dataclass(frozen=True, slots=True)
class _Services:
    """Concrete adapters sharing the test database alias."""

    body_store: StatutorySourceBodyStore
    source_repository: DjangoStatutorySourceRepository
    source_reader: DjangoFinancialAvailabilitySourceReader
    records: DjangoFinancialAvailabilityGovernanceRepository
    owner_events: DjangoFinancialAvailabilityOwnerEventRepository
    authorizer: DjangoFinancialAvailabilityPermissionAuthorizer


@dataclass(frozen=True, slots=True)
class _SourceSeed:
    """One synthetic retained body and an explicit source-known cutoff."""

    revision: StatutorySourceDocumentRevision
    capture_id: UUID
    known_at: datetime
    source_reference: StatutorySourceCaptureReference


@contextmanager
def _register(operation: _Operation) -> Iterator[str]:
    """Register one server-held test action under a random selector."""

    key = uuid4().hex
    _OPERATIONS[key] = operation
    try:
        yield key
    finally:
        _OPERATIONS.pop(key, None)


def _database_now(using: str = DEFAULT_DB_ALIAS) -> datetime:
    """Sample PostgreSQL wall time for test bounds, not as an inferred source time."""

    with connections[using].cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        row = cursor.fetchone()
    assert row is not None and type(row[0]) is datetime and row[0].tzinfo is not None
    return row[0].astimezone(UTC)


def _proof_from_authenticated_request(
    request: HttpRequest,
) -> FinancialAvailabilitySessionRequestProof:
    """Build test input from a real Django-authenticated request and DB session."""

    user = request.user
    session_key = request.session.session_key
    alias = user._state.db
    if (
        not user.is_authenticated
        or type(user.pk) is not int
        or type(session_key) is not str
        or not session_key
        or type(alias) is not str
        or not alias
    ):
        raise AuthenticationError("The test request has no persisted authenticated session.")
    return FinancialAvailabilitySessionRequestProof(
        user_id=user.pk,
        session_key=session_key,
        request_authenticated_at=timezone.now().astimezone(UTC),
        request_user_database_alias=alias,
        database_alias=alias,
    )


def _dispatch_test_request(request: HttpRequest) -> JsonResponse:
    """Exercise the Application boundary from a normal Django session request."""

    if request.method not in {"GET", "POST"}:
        return JsonResponse({"outcome": "method_not_allowed"}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({"outcome": "unauthenticated"}, status=401)
    selector = (
        request.GET.get("operation") if request.method == "GET" else request.POST.get("operation")
    )
    if type(selector) is not str or selector not in _OPERATIONS:
        return JsonResponse({"outcome": "unknown_test_operation"}, status=404)
    operation = _OPERATIONS[selector]
    try:
        proof = _proof_from_authenticated_request(request)
        operation.proof = proof
        if operation.action == "proof":
            return JsonResponse({"outcome": "authenticated"}, status=200)
        if operation.action == "apply":
            operation.persisted_record, operation.event = (
                apply_financial_availability_governance_from_request(
                    request,
                    operation.record,
                    reason="Synthetic PG contract test",
                    records=operation.services.records,
                    owner_events=operation.services.owner_events,
                )
            )
        elif operation.action == "revoke":
            if operation.apply_event is None:
                raise DataValidationError("The server-side test apply identity is absent.")
            operation.event = revoke_financial_availability_governance_from_request(
                request,
                operation.record,
                operation.apply_event,
                reason="Synthetic PG contract test revoke",
                records=operation.services.records,
                owner_events=operation.services.owner_events,
            )
        else:
            raise DataValidationError("The server-side test action is unsupported.")
    except AuthenticationError:
        return JsonResponse({"outcome": "authentication_rejected"}, status=401)
    except AuthorizationError:
        return JsonResponse({"outcome": "authorization_rejected"}, status=403)
    except DataValidationError:
        return JsonResponse({"outcome": "candidate_rejected"}, status=409)
    assert operation.event is not None
    return JsonResponse(
        {
            "outcome": "success",
            "event_id": str(operation.event.event_id),
            "event_sha256": operation.event.event_sha256,
        },
        status=201,
    )


urlpatterns = [path("_test/c2/", _dispatch_test_request)]


def _services(tmp_path: Path) -> _Services:
    """Construct real ORM/source adapters without calling external providers."""

    body_store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
    source_repository = DjangoStatutorySourceRepository(
        body_store=body_store,
        using=DEFAULT_DB_ALIAS,
        # The captured-source fixture uses an explicit DB clock. The dedicated
        # contention test below uses the production default to cover its lock.
        clock=lambda: _database_now(DEFAULT_DB_ALIAS),
    )
    source_reader = DjangoFinancialAvailabilitySourceReader(
        repository=source_repository,  # Requires Root's public database_alias adoption patch.
        body_store=body_store,
        using=DEFAULT_DB_ALIAS,
    )
    records = DjangoFinancialAvailabilityGovernanceRepository(using=DEFAULT_DB_ALIAS)
    owner_events = DjangoFinancialAvailabilityOwnerEventRepository(
        using=DEFAULT_DB_ALIAS,
        source_reader=source_reader,
    )
    authorizer = DjangoFinancialAvailabilityPermissionAuthorizer(using=DEFAULT_DB_ALIAS)
    return _Services(
        body_store=body_store,
        source_repository=source_repository,
        source_reader=source_reader,
        records=records,
        owner_events=owner_events,
        authorizer=authorizer,
    )


def _append_source(services: _Services) -> _SourceSeed:
    """Use the existing retained-source use case with synthetic exact bytes."""

    capture_id = uuid4()
    revision = StatutorySourceDocumentRevision(
        issuer="Synthetic C2 PG mechanics fixture",
        document_id=f"c2-pg-{uuid4().hex}",
        source_version="fixture-v1",
        canonical_url="https://example.invalid/c2-mechanics.pdf",
        title="Synthetic C2 mechanics fixture",
        legal_number="C2-PG-MECHANICS",
        publication_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=date(2026, 1, 1),
        ),
        effective_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.UNKNOWN,
        ),
        body_sha256=sha256(_TEST_BODY).hexdigest(),
        body_size_bytes=len(_TEST_BODY),
    )
    RetainStatutorySourceDocumentUseCase(
        body_store=services.body_store,
        document_repository=services.source_repository,
    ).execute(
        revision=revision,
        capture_id=capture_id,
        captured_at=_database_now() - timedelta(milliseconds=5),
        content_type="application/pdf",
        body=_TEST_BODY,
    )
    known_at = _database_now()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        source_read = services.source_reader.read_exact_capture(
            issuer=revision.issuer,
            document_id=revision.document_id,
            source_version=revision.source_version,
            capture_id=capture_id,
            known_at=known_at,
        )
    assert source_read is not None
    return _SourceSeed(
        revision=revision,
        capture_id=capture_id,
        known_at=known_at,
        source_reference=source_read.reference,
    )


def _opening_record(source: _SourceSeed) -> FinancialAvailabilityGovernanceRecord:
    """Build one explicit test rule; its phase/time are not a business default."""

    reference = source.source_reference
    proposal = ExchangeSessionOpeningRuleProposal(
        exchange="SZSE",
        phase=ExchangeSessionOpeningPhase.OPENING_CALL_AUCTION,
        rule_version="synthetic-pg-v1",
        source_uri=reference.canonical_url,
        source_body_sha256=reference.body_sha256,
        effective_start=date(2026, 1, 1),
        effective_end=date(2026, 12, 31),
        timezone_name="Asia/Shanghai",
        local_open_time=time(9, 15),
        first_seen_at=reference.first_seen_at,
        source_recorded_at=reference.revision_recorded_at,
    )
    return FinancialAvailabilityGovernanceRecord(
        record_id=f"c2-synthetic-rule-{uuid4().hex}",
        record_version="synthetic-pg-v1",
        exchange="SZSE",
        kind=FinancialAvailabilityRecordKind.OPENING_RULE,
        content=proposal,
        recorded_at=reference.capture_recorded_at,
        source=reference,
    )


def _policy_record(*, record_id: str | None = None) -> FinancialAvailabilityGovernanceRecord:
    """Build one explicit test policy without selecting production values."""

    now = _database_now()
    selected_id = record_id or f"c2-synthetic-policy-{uuid4().hex}"
    policy = FinancialDisclosureAvailabilityPolicy.create(
        policy_id=selected_id,
        policy_version="synthetic-pg-v1",
        exchange="SZSE",
        opening_phase=ExchangeSessionOpeningPhase.CONTINUOUS_AUCTION,
        effective_start=date(2026, 1, 1),
        effective_end=date(2026, 12, 31),
        calendar_response_max_age_seconds=31,
        first_seen_at=now,
        recorded_at=now,
    )
    return FinancialAvailabilityGovernanceRecord(
        record_id=selected_id,
        record_version="synthetic-pg-v1",
        exchange="SZSE",
        kind=FinancialAvailabilityRecordKind.DISCLOSURE_POLICY,
        content=policy,
        recorded_at=now,
    )


def _permission_for_c2() -> Permission:
    """Load the migrated app permission, creating no alternate auth mechanism."""

    content_type = ContentType.objects.db_manager(DEFAULT_DB_ALIAS).get_for_model(
        FinancialAvailabilityGovernanceRecordModel,
        for_concrete_model=False,
    )
    permission, _created = Permission.objects.using(DEFAULT_DB_ALIAS).get_or_create(
        content_type=content_type,
        codename=FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME,
        defaults={"name": "Can manage financial availability governance"},
    )
    return permission


def _authenticated_client(grant_kind: str) -> tuple[Client, object, Permission, Group | None]:
    """Authenticate a real Django User and assign its direct or group grant."""

    user_model = get_user_model()
    user = user_model._default_manager.db_manager(DEFAULT_DB_ALIAS).create_user(
        username=f"c2-pg-{uuid4().hex}",
        password="c2-test-password-only",
    )
    permission = _permission_for_c2()
    group: Group | None = None
    if grant_kind == "direct":
        user.user_permissions.add(permission)
    elif grant_kind == "group":
        group = Group.objects.using(DEFAULT_DB_ALIAS).create(name=f"c2-pg-{uuid4().hex}")
        group.permissions.add(permission)
        user.groups.add(group)
    else:
        raise AssertionError("test grant kind must be direct or group")
    client = Client()
    assert client.login(username=user.get_username(), password="c2-test-password-only") is True
    return client, user, permission, group


def _pg_lock_waiting(pid: int) -> bool:
    """Observe one real PostgreSQL backend blocked by another backend."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM pg_stat_activity AS activity
                 WHERE activity.pid = %s
                   AND activity.wait_event_type = 'Lock'
                   AND cardinality(pg_blocking_pids(activity.pid)) > 0
            )
            """,
            [pid],
        )
        row = cursor.fetchone()
    return row is not None and row[0] is True


def _wait_for_pg_lock(pid: int, *, timeout_seconds: float = 5.0) -> bool:
    """Poll PostgreSQL's lock graph for a bounded test interval."""

    deadline = time_module.monotonic() + timeout_seconds
    while time_module.monotonic() < deadline:
        if _pg_lock_waiting(pid):
            return True
        time_module.sleep(0.01)
    return False


@pytest.mark.parametrize("grant_kind", ("direct", "group"))
@override_settings(ROOT_URLCONF=__name__)
def test_normal_authenticated_request_applies_and_revokes_with_exact_pit_and_hashes(
    grant_kind: str,
    tmp_path: Path,
) -> None:
    """Exercise real request session, both grant routes, append events, and PIT read."""

    if connection.vendor != "postgresql":
        pytest.skip("C2 Owner write contract requires native PostgreSQL")
    services = _services(tmp_path)
    client, _user, _permission, _group = _authenticated_client(grant_kind)
    tx_started: datetime
    source: _SourceSeed
    record: FinancialAvailabilityGovernanceRecord
    apply_event: FinancialAvailabilityOwnerEventIdentity
    persisted: FinancialAvailabilityGovernanceRecord
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        with connection.cursor() as cursor:
            cursor.execute("SELECT transaction_timestamp()")
            row = cursor.fetchone()
        assert row is not None
        tx_started = row[0].astimezone(UTC)
        source = _append_source(services)
        assert tx_started < source.source_reference.capture_recorded_at <= source.known_at
        record = _opening_record(source)
        operation = _Operation(
            action="apply",
            record=record,
            source_known_at=source.known_at,
            services=services,
        )
        with _register(operation) as selector:
            response = client.post(_URL_PATH, data={"operation": selector})
        assert response.status_code == 201
        assert operation.proof is not None
        assert operation.persisted_record is not None
        assert operation.event is not None
        persisted = operation.persisted_record
        apply_event = operation.event
        assert source.source_reference.capture_recorded_at <= source.known_at
        assert apply_event.permission_verified_at >= operation.proof.request_authenticated_at
        expected_result = persisted.content.materialize_applied_rule(
            recorded_at=persisted.recorded_at,
            approved_at=apply_event.occurred_at,
        )
        assert apply_event.resulting_content_sha256 == expected_result.rule_sha256
        assert apply_event.record_content_sha256 == persisted.content_sha256
        assert apply_event.event_sha256 == apply_event.computed_event_sha256()

    time_module.sleep(0.01)
    pre_revoke_known_at = _database_now()
    revoke_operation = _Operation(
        action="revoke",
        record=persisted,
        apply_event=apply_event,
        services=services,
    )
    with _register(revoke_operation) as selector:
        response = client.post(_URL_PATH, data={"operation": selector})
    assert response.status_code == 201
    revoke_event = revoke_operation.event
    assert revoke_event is not None

    prior = read_financial_availability_governance(
        GetFinancialAvailabilityGovernanceQuery(
            kind=FinancialAvailabilityRecordKind.OPENING_RULE,
            exchange="SZSE",
            effective_on=date(2026, 6, 1),
            known_at=pre_revoke_known_at,
        ),
        records=services.records,
        owner_events=services.owner_events,
        source_reader=services.source_reader,
    )
    assert prior.known_at == pre_revoke_known_at
    assert prior.apply_event == apply_event
    assert prior.source_read is not None
    assert prior.source_read.known_at == pre_revoke_known_at
    with pytest.raises(DataValidationError, match="No applied C2 governance version"):
        read_financial_availability_governance(
            GetFinancialAvailabilityGovernanceQuery(
                kind=FinancialAvailabilityRecordKind.OPENING_RULE,
                exchange="SZSE",
                effective_on=date(2026, 6, 1),
                known_at=_database_now(),
            ),
            records=services.records,
            owner_events=services.owner_events,
            source_reader=services.source_reader,
        )
    assert revoke_event.predecessor_apply_event_id == apply_event.event_id
    assert revoke_event.predecessor_apply_event_sha256 == apply_event.event_sha256


@override_settings(ROOT_URLCONF=__name__)
def test_unauthenticated_request_and_expired_real_session_are_rejected(tmp_path: Path) -> None:
    """Reject missing and expired database sessions before appending a C2 row."""

    if connection.vendor != "postgresql":
        pytest.skip("C2 Owner authorization contract requires native PostgreSQL")
    services = _services(tmp_path)
    user_client, _user, _permission, _group = _authenticated_client("direct")
    record = _policy_record()
    logged_operation = _Operation(action="proof", record=record, services=services)
    with _register(logged_operation) as selector:
        assert user_client.get(_URL_PATH, data={"operation": selector}).status_code == 200
    proof = logged_operation.proof
    assert proof is not None

    anonymous = Client()
    anonymous_operation = _Operation(
        action="apply",
        record=record,
        source_known_at=_database_now(),
        services=services,
    )
    with _register(anonymous_operation) as selector:
        response = anonymous.post(_URL_PATH, data={"operation": selector})
    assert response.status_code == 401
    assert not FinancialAvailabilityGovernanceRecordModel.objects.filter(
        record_id=record.record_id
    ).exists()

    Session.objects.using(DEFAULT_DB_ALIAS).filter(session_key=proof.session_key).update(
        expire_date=_database_now() - timedelta(seconds=1)
    )
    with pytest.raises(AuthenticationError, match="session no longer authenticates"):
        append_and_apply_financial_availability_governance(
            record,
            proof=proof,
            reason="Expired session must fail",
            source_known_at=_database_now(),
            records=services.records,
            owner_events=services.owner_events,
            authorizer=services.authorizer,
        )
    assert not FinancialAvailabilityGovernanceRecordModel.objects.filter(
        record_id=record.record_id
    ).exists()


@override_settings(ROOT_URLCONF=__name__)
@pytest.mark.parametrize("grant_kind", ("direct", "group"))
@override_settings(ROOT_URLCONF=__name__)
def test_revoked_direct_or_group_grant_is_reloaded_before_apply(
    grant_kind: str,
    tmp_path: Path,
) -> None:
    """A real request session cannot reuse cached Django permission after grant removal."""

    if connection.vendor != "postgresql":
        pytest.skip("C2 Owner authorization contract requires native PostgreSQL")
    services = _services(tmp_path)
    client, user, permission, group = _authenticated_client(grant_kind)
    record = _policy_record()
    proof_operation = _Operation(action="proof", record=record, services=services)
    with _register(proof_operation) as selector:
        assert client.get(_URL_PATH, data={"operation": selector}).status_code == 200
    proof = proof_operation.proof
    assert proof is not None
    if grant_kind == "direct":
        user.user_permissions.remove(permission)
    else:
        assert group is not None
        group.permissions.remove(permission)
    with pytest.raises(AuthorizationError, match="lacks the dedicated Django permission"):
        append_and_apply_financial_availability_governance(
            record,
            proof=proof,
            reason="Revoked grant must fail",
            source_known_at=_database_now(),
            records=services.records,
            owner_events=services.owner_events,
            authorizer=services.authorizer,
        )
    assert not FinancialAvailabilityGovernanceRecordModel.objects.filter(
        record_id=record.record_id
    ).exists()


@override_settings(ROOT_URLCONF=__name__)
def test_wrong_auth_database_alias_is_rejected_before_session_lookup(tmp_path: Path) -> None:
    """A proof relabeled to another alias cannot authorize this repository."""

    if connection.vendor != "postgresql":
        pytest.skip("C2 Owner authorization contract requires native PostgreSQL")
    services = _services(tmp_path)
    client, _user, _permission, _group = _authenticated_client("direct")
    proof_operation = _Operation(action="proof", record=_policy_record(), services=services)
    with _register(proof_operation) as selector:
        assert client.get(_URL_PATH, data={"operation": selector}).status_code == 200
    assert proof_operation.proof is not None
    wrong_alias_proof = replace(
        proof_operation.proof,
        request_user_database_alias="non_default_test_alias",
        database_alias="non_default_test_alias",
    )
    with pytest.raises(AuthorizationError, match="different database alias"):
        with services.authorizer.lock_authorized_principal(wrong_alias_proof):
            pytest.fail("wrong-alias session reached the protected body")


def test_source_reader_share_locks_both_tables_against_a_capture_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Show the C2 exact source read's two SHARE locks block append through commit."""

    if connection.vendor != "postgresql":
        pytest.skip("C2 statutory-source SHARE-lock contract requires native PostgreSQL")
    services = _services(tmp_path)
    seed = _append_source(services)
    second_capture_id = uuid4()
    second_capture_at = _database_now() - timedelta(milliseconds=1)
    # The test source is synthetic and explicitly not an official-source claim.
    body_reference = services.body_store.store(second_capture_id, _TEST_BODY)
    second_capture = RetainedStatutorySourceDocumentCapture(
        capture_id=second_capture_id,
        revision=seed.revision,
        captured_at=second_capture_at,
        content_type="application/pdf",
        body_reference=body_reference,
    )
    writer_repository = DjangoStatutorySourceRepository(
        body_store=services.body_store,
        using=DEFAULT_DB_ALIAS,
    )
    locked = threading.Event()
    release = threading.Event()
    reader_pid: list[int] = []
    writer_pid: list[int] = []
    reader_results: list[object] = []
    worker_errors: list[BaseException] = []

    original_lock = services.source_reader._lock_source_tables

    def pause_after_source_fence() -> None:
        """Hold the actual reader's locks until a separate writer is observed waiting."""

        original_lock()
        with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            row = cursor.fetchone()
        assert row is not None
        reader_pid.append(row[0])
        locked.set()
        if not release.wait(timeout=10.0):
            raise AssertionError("test failed to release source reader fence")

    monkeypatch.setattr(services.source_reader, "_lock_source_tables", pause_after_source_fence)

    def read_source() -> None:
        worker_connection = connections[DEFAULT_DB_ALIAS]
        try:
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                reader_results.append(
                    services.source_reader.read_exact_capture(
                        issuer=seed.revision.issuer,
                        document_id=seed.revision.document_id,
                        source_version=seed.revision.source_version,
                        capture_id=seed.capture_id,
                        known_at=seed.known_at,
                    )
                )
        except BaseException as error:
            worker_errors.append(error)
        finally:
            worker_connection.close()

    def append_capture() -> None:
        worker_connection = connections[DEFAULT_DB_ALIAS]
        try:
            worker_connection.ensure_connection()
            with worker_connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                row = cursor.fetchone()
            assert row is not None
            writer_pid.append(row[0])
            RetainStatutorySourceDocumentUseCase(
                body_store=services.body_store,
                document_repository=writer_repository,
            ).execute(
                revision=seed.revision,
                capture_id=second_capture_id,
                captured_at=second_capture.captured_at,
                content_type=second_capture.content_type,
                body=_TEST_BODY,
            )
        except BaseException as error:
            worker_errors.append(error)
        finally:
            worker_connection.close()

    reader_thread = threading.Thread(target=read_source, daemon=True)
    writer_thread = threading.Thread(target=append_capture, daemon=True)
    try:
        reader_thread.start()
        assert locked.wait(timeout=5.0)
        assert reader_pid
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                  FROM pg_locks
                 WHERE pid = %s
                   AND locktype = 'relation'
                   AND granted
                   AND mode = 'ShareLock'
                   AND relation IN (
                       to_regclass('public.dc_statutory_source_revision')::oid,
                       to_regclass('public.dc_statutory_source_capture')::oid
                   )
                """,
                [reader_pid[0]],
            )
            row = cursor.fetchone()
        assert row is not None and row[0] == 2
        writer_thread.start()
        deadline = time_module.monotonic() + 5.0
        while time_module.monotonic() < deadline and not writer_pid:
            time_module.sleep(0.01)
        assert writer_pid
        assert _wait_for_pg_lock(writer_pid[0])
    finally:
        release.set()
        if reader_thread.ident is not None:
            reader_thread.join(timeout=10.0)
        if writer_thread.ident is not None:
            writer_thread.join(timeout=10.0)

    assert not reader_thread.is_alive()
    assert not writer_thread.is_alive()
    assert not worker_errors
    assert len(reader_results) == 1 and reader_results[0] is not None
    assert services.source_repository.get_capture(second_capture_id) is not None


@override_settings(ROOT_URLCONF=__name__)
def test_revoke_event_clocks_are_sampled_after_the_config_row_lock_wait(
    tmp_path: Path,
) -> None:
    """A blocked revoke must use a fresh PG wall clock after config and actor locks."""

    if connection.vendor != "postgresql":
        pytest.skip("C2 Owner event-lock contract requires native PostgreSQL")
    services = _services(tmp_path)
    client, _user, _permission, _group = _authenticated_client("direct")
    record = _policy_record()
    apply_operation = _Operation(
        action="apply",
        record=record,
        source_known_at=_database_now(),
        services=services,
    )
    with _register(apply_operation) as selector:
        response = client.post(_URL_PATH, data={"operation": selector})
    assert response.status_code == 201
    assert apply_operation.persisted_record is not None
    assert apply_operation.event is not None
    persisted = apply_operation.persisted_record
    apply_event = apply_operation.event
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    response_status: list[int] = []
    worker_errors: list[BaseException] = []
    worker_pid: list[int] = []

    def revoke_request() -> None:
        worker_connection = connections[DEFAULT_DB_ALIAS]
        try:
            worker_connection.ensure_connection()
            with worker_connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                row = cursor.fetchone()
            assert row is not None
            worker_pid.append(row[0])
            worker_client = Client()
            worker_client.cookies[settings.SESSION_COOKIE_NAME] = cookie
            revoke_operation = _Operation(
                action="revoke",
                record=persisted,
                apply_event=apply_event,
                services=services,
            )
            with _register(revoke_operation) as selector:
                response = worker_client.post(_URL_PATH, data={"operation": selector})
            response_status.append(response.status_code)
            if response.status_code == 201:
                assert revoke_operation.event is not None
                _REVOKE_RESULTS.append(revoke_operation.event)
        except BaseException as error:
            worker_errors.append(error)
        finally:
            worker_connection.close()

    _REVOKE_RESULTS: list[FinancialAvailabilityOwnerEventIdentity] = []
    worker = threading.Thread(target=revoke_request, daemon=True)
    try:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            locked_record = (
                FinancialAvailabilityGovernanceRecordModel.objects.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .get(record_id=persisted.record_id, record_version=persisted.record_version)
            )
            assert locked_record.content_sha256 == persisted.content_sha256
            worker.start()
            deadline = time_module.monotonic() + 5.0
            while time_module.monotonic() < deadline and not worker_pid:
                time_module.sleep(0.01)
            assert worker_pid
            assert _wait_for_pg_lock(worker_pid[0])
            released_at = _database_now()
        worker.join(timeout=10.0)
    finally:
        if worker.ident is not None:
            worker.join(timeout=10.0)

    assert not worker.is_alive()
    assert not worker_errors
    assert response_status == [201]
    assert len(_REVOKE_RESULTS) == 1
    revoke_event = _REVOKE_RESULTS[0]
    assert revoke_event.permission_verified_at < released_at
    assert revoke_event.occurred_at >= released_at
    assert revoke_event.recorded_at >= revoke_event.occurred_at
    assert revoke_event.predecessor_apply_event_id == apply_event.event_id
    assert revoke_event.predecessor_apply_event_sha256 == apply_event.event_sha256


@override_settings(ROOT_URLCONF=__name__)
def test_current_pair_locks_both_kinds_and_returns_one_post_lock_cutoff(
    tmp_path: Path,
) -> None:
    """Read exact current rule/policy and source in one ambient RC UOW."""

    if connection.vendor != "postgresql":
        pytest.skip("C2 current governance requires native PostgreSQL")
    services = _services(tmp_path)
    client, _user, _permission, _group = _authenticated_client("direct")
    source = _append_source(services)
    opening_record = _opening_record(source)
    policy_record = _policy_record()
    operations: list[_Operation] = []
    for record in (opening_record, policy_record):
        operation = _Operation(
            action="apply",
            record=record,
            source_known_at=source.known_at,
            services=services,
        )
        operations.append(operation)
        with _register(operation) as selector:
            response = client.post(_URL_PATH, data={"operation": selector})
        assert response.status_code == 201
        assert operation.event is not None

    assert operations[0].event is not None
    assert operations[1].event is not None
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        pair = resolve_current_financial_availability_governance(
            ResolveCurrentFinancialAvailabilityGovernanceQuery(
                exchange="SZSE",
                effective_on=date(2026, 6, 1),
            ),
            records=services.records,
            owner_events=services.owner_events,
            source_reader=services.source_reader,
        )

    assert pair.known_at >= operations[0].event.recorded_at
    assert pair.known_at >= operations[1].event.recorded_at
    assert pair.checked_at >= pair.known_at
    assert pair.opening_rule.record == operations[0].persisted_record
    assert pair.opening_rule.apply_event == operations[0].event
    assert pair.disclosure_policy.record == operations[1].persisted_record
    assert pair.disclosure_policy.apply_event == operations[1].event
    assert pair.opening_rule.source_read is not None
    assert pair.opening_rule.source_read.known_at == pair.known_at


def test_current_shared_scope_fence_excludes_apply_or_revoke_scope_writer() -> None:
    """The current read shared lock conflicts with the common C2 writer key."""

    if connection.vendor != "postgresql":
        pytest.skip("C2 scope advisory fence requires native PostgreSQL")
    records = DjangoFinancialAvailabilityGovernanceRepository(using=DEFAULT_DB_ALIAS)
    barrier = threading.Barrier(2)
    worker_codes: list[str] = []
    worker_errors: list[BaseException] = []

    def try_writer_scope() -> None:
        worker_connection = connections[DEFAULT_DB_ALIAS]
        try:
            worker_connection.ensure_connection()
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                barrier.wait(timeout=5.0)
                try:
                    records.lock_change_scope(
                        kind=FinancialAvailabilityRecordKind.OPENING_RULE,
                        exchange="SZSE",
                    )
                except DataValidationError as error:
                    worker_codes.append(error.code)
        except BaseException as error:
            worker_errors.append(error)
        finally:
            worker_connection.close()

    worker = threading.Thread(target=try_writer_scope, daemon=True)
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        records.require_caller_owned_current_uow()
        records.lock_current_scopes(((FinancialAvailabilityRecordKind.OPENING_RULE, "SZSE"),))
        worker.start()
        barrier.wait(timeout=5.0)
        worker.join(timeout=5.0)
        assert not worker.is_alive()
        assert worker_codes == ["FIN_AVAILABILITY_SCOPE_LOCK_BUSY"]
        assert not worker_errors
    if worker.ident is not None:
        worker.join(timeout=5.0)


@pytest.fixture(autouse=True)
def _require_owned_native_test_database(
    django_db_use_migrations: bool,
    transactional_db: None,
) -> None:
    """Require full migrations and the explicit isolated PostgreSQL TEST.NAME."""

    if connection.vendor != "postgresql" or not django_db_use_migrations:
        pytest.skip("native financial availability contracts require migrated PostgreSQL")
    assert_native_postgres_test_database()
