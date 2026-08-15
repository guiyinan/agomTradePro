"""Opt-in PostgreSQL concurrency evidence for the M1 audit ledger/outbox.

The default project settings use SQLite, so this module deliberately skips
without the explicit evidence flag.  It never treats SQLite as PostgreSQL
evidence.  For an actual run use the isolated settings module
``tests.settings_audit_postgres_concurrency`` and a disposable database whose
name contains both ``audit`` and ``test``.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from urllib.parse import unquote, urlsplit

import pytest
from django.db import close_old_connections, connection, connections
from django.db.migrations.state import ProjectState

from apps.audit.domain.system_audit_event import JSONValue, SystemAuditEvent
from apps.audit.infrastructure import system_audit_repository as system_audit_repository_module
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
    SystemAuditOutboxClaim,
    SystemAuditOutboxConflict,
)
from apps.audit.infrastructure.system_audit_repository import (
    DjangoSystemAuditEventRepository,
    SystemAuditConflict,
)
from tests.unit.audit.test_system_audit_event import make_event

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
_EVIDENCE_FLAG = "AGOM_AUDIT_PG_CONCURRENCY_EVIDENCE"
_EVIDENCE_URL = "AGOM_AUDIT_PG_TEST_DATABASE_URL"


class _FixedClock:
    """Deterministic aware clock for isolated concurrency runs."""

    def now(self) -> datetime:
        return NOW + timedelta(days=1)


@dataclass(frozen=True, slots=True)
class _AppendResult:
    status: str
    event_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _ClaimResult:
    status: str
    claim: SystemAuditOutboxClaim | None = None
    error: str | None = None


def _require_postgresql_evidence() -> None:
    """Skip by default and fail closed for a malformed explicit opt-in."""

    if os.environ.get(_EVIDENCE_FLAG, "").strip() != "1":
        pytest.skip("PostgreSQL audit concurrency evidence is opt-in; " f"set {_EVIDENCE_FLAG}=1")
    database_url = os.environ.get(_EVIDENCE_URL, "").strip()
    if not database_url:
        pytest.fail(
            f"{_EVIDENCE_URL} is required when {_EVIDENCE_FLAG}=1; "
            "SQLite/default settings are not evidence"
        )
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        pytest.fail(f"{_EVIDENCE_URL} must use a PostgreSQL URL")
    if parsed.hostname is None or parsed.hostname.lower() not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "postgres",
        "postgresql",
        "db",
    }:
        pytest.fail(f"{_EVIDENCE_URL} must use a local/test-service PostgreSQL host")
    configured_name = unquote(parsed.path.removeprefix("/"))
    configured_lower = configured_name.lower()
    if "audit" not in configured_lower or "test" not in configured_lower:
        pytest.fail(f"{_EVIDENCE_URL} must target a disposable database containing audit and test")
    if connection.vendor != "postgresql":
        pytest.fail(
            "PostgreSQL audit concurrency evidence refused: "
            f"active database vendor is {connection.vendor!r}, not PostgreSQL"
        )
    runtime_name = str(connection.settings_dict.get("NAME", ""))
    runtime_lower = runtime_name.lower()
    if not runtime_lower.startswith("test_") or configured_lower not in runtime_lower:
        pytest.fail(
            "PostgreSQL audit concurrency evidence refused: active database is not "
            "the isolated pytest database"
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
    if row is None or str(row[0]) != runtime_name:
        pytest.fail("PostgreSQL audit concurrency evidence refused: database identity mismatch")


@pytest.fixture(scope="module", autouse=True)
def _audit_pg_schema(django_db_setup: object, django_db_blocker: object) -> Iterator[None]:
    """Create only the two zero-seed audit tables in the isolated test DB."""

    created_tables = False
    migration = importlib.import_module(
        "apps.audit.migrations.0011_systemauditeventmodel"
    ).Migration
    before = ProjectState()
    after = before.clone()
    for operation in migration.operations:
        operation.state_forwards("audit", after)
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        _require_postgresql_evidence()
        required_tables = {
            SystemAuditEventModel._meta.db_table,
            SystemAuditOutboxModel._meta.db_table,
        }
        existing_tables = set(connection.introspection.table_names())
        present_required = required_tables.intersection(existing_tables)
        if present_required and present_required != required_tables:
            pytest.fail(
                "PostgreSQL audit concurrency evidence requires both audit tables or neither; "
                "refusing to continue with a partially initialized database"
            )
        if not present_required:
            with connection.schema_editor() as editor:
                for operation in migration.operations:
                    operation.database_forwards("audit", editor, before, after)
            created_tables = True
        else:
            with connection.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) FROM "audit_system_event"')
                event_count = int(cursor.fetchone()[0])
                cursor.execute('SELECT COUNT(*) FROM "audit_system_outbox"')
                outbox_count = int(cursor.fetchone()[0])
            if event_count or outbox_count:
                pytest.fail(
                    "PostgreSQL audit concurrency evidence requires an empty dedicated database; "
                    "refusing to delete existing audit rows"
                )
    yield
    if created_tables:
        with django_db_blocker.unblock():  # type: ignore[attr-defined]
            with connection.schema_editor() as editor:
                for operation in reversed(migration.operations):
                    operation.database_backwards("audit", editor, after, before)


@pytest.fixture(autouse=True)
def _clear_audit_pg_tables(django_db_blocker: object) -> Iterator[None]:
    """Clear only rows created by this harness before each evidence case."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with connection.cursor() as cursor:
            cursor.execute('TRUNCATE TABLE "audit_system_outbox", "audit_system_event"')
    yield


def _event(
    *,
    event_id: str,
    idempotency_key: str,
    sequence_no: int = 1,
    predecessor_hash: str | None = None,
    recorded_at: datetime = NOW,
    stream_id: str = "dataset:macro.pmi",
    detail: Mapping[str, JSONValue] | None = None,
) -> SystemAuditEvent:
    """Build a hash-consistent event with only the identity fields varied."""

    base = make_event()
    return SystemAuditEvent.create(
        event_id=event_id,
        event_version=base.event_version,
        schema_version=base.schema_version,
        category=base.category,
        event_type=base.event_type,
        owner=base.owner,
        write_policy=base.write_policy,
        outcome=base.outcome,
        severity=base.severity,
        reason_codes=base.reason_codes,
        occurred_at=base.occurred_at,
        recorded_at=recorded_at,
        observed_at=base.observed_at,
        actor=base.actor,
        source_app=base.source_app,
        source_component=base.source_component,
        source_surface=base.source_surface,
        correlations=base.correlations,
        resource=base.resource,
        dataset_key=base.dataset_key,
        provider_key=base.provider_key,
        capability=base.capability,
        publication_id=base.publication_id,
        evidence_refs=base.evidence_refs,
        scope=base.scope,
        detail_schema=base.detail_schema,
        detail=detail if detail is not None else base.detail,
        stream_id=stream_id,
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=idempotency_key,
    )


def _append_in_worker(
    event: SystemAuditEvent,
    barrier: Barrier,
    expected_predecessor_hash: str | None,
    recorded_at: datetime,
) -> _AppendResult:
    """Append from a fresh Django connection and return bounded evidence."""

    close_old_connections()
    try:
        repository = DjangoSystemAuditEventRepository(clock=_FixedClock())
        with repository.atomic():
            barrier.wait(timeout=10)
            repository.append(
                event,
                expected_predecessor_hash=expected_predecessor_hash,
                recorded_at=recorded_at,
            )
        return _AppendResult(status="winner", event_id=event.event_id)
    except SystemAuditConflict as error:
        return _AppendResult(status="conflict", event_id=event.event_id, error=str(error))
    finally:
        connections["default"].close()


def _repository() -> DjangoSystemAuditEventRepository:
    return DjangoSystemAuditEventRepository(clock=_FixedClock())


def _outbox_repository() -> DjangoSystemAuditOutboxRepository:
    return DjangoSystemAuditOutboxRepository(clock=_FixedClock())


def test_empty_stream_first_winner_is_postgresql_unique_and_not_sqlite_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two empty-stream roots yield one winner and one exact conflict."""

    repository = _repository()
    first = _event(event_id="evt-empty-a", idempotency_key="fetch:empty:a")
    second = _event(event_id="evt-empty-b", idempotency_key="fetch:empty:b")
    original_claim = getattr(system_audit_repository_module, "_claim_system_audit_insert")

    @contextmanager
    def _gated_claim(event_id: str, content_hash: str) -> Iterator[None]:
        """Pause after both workers restored the same empty stream."""

        with original_claim(event_id, content_hash):
            barrier.wait(timeout=10)
            yield

    monkeypatch.setattr(
        system_audit_repository_module,
        "_claim_system_audit_insert",
        _gated_claim,
    )
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures: tuple[Future[_AppendResult], Future[_AppendResult]] = (
            executor.submit(_append_in_worker, first, barrier, None, NOW),
            executor.submit(_append_in_worker, second, barrier, None, NOW),
        )
        results = tuple(future.result(timeout=15) for future in futures)

    assert sorted(result.status for result in results) == ["conflict", "winner"]
    conflict = next(result for result in results if result.status == "conflict")
    assert conflict.error == "system audit append lost its first-winner race"
    events = repository.list_events(stream_id=first.stream_id, as_of=NOW)
    assert len(events) == 1
    assert events[0] in (first, second)


def test_same_predecessor_cas_allows_one_successor_without_a_fork() -> None:
    """Two successors of one head cannot both commit on PostgreSQL."""

    repository = _repository()
    root = _event(event_id="evt-cas-root", idempotency_key="fetch:cas:root")
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    first = _event(
        event_id="evt-cas-a",
        idempotency_key="fetch:cas:a",
        sequence_no=2,
        predecessor_hash=root.content_hash,
        recorded_at=LATER,
    )
    second = _event(
        event_id="evt-cas-b",
        idempotency_key="fetch:cas:b",
        sequence_no=2,
        predecessor_hash=root.content_hash,
        recorded_at=LATER,
    )
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(_append_in_worker, first, barrier, root.content_hash, LATER),
            executor.submit(_append_in_worker, second, barrier, root.content_hash, LATER),
        )
        results = tuple(future.result(timeout=15) for future in futures)

    assert sorted(result.status for result in results) == ["conflict", "winner"]
    winner_id = next(result.event_id for result in results if result.status == "winner")
    events = repository.list_events(stream_id=root.stream_id, as_of=LATER)
    assert len(events) == 2
    assert events[0] == root
    assert events[1].event_id == winner_id
    assert events[1].predecessor_hash == root.content_hash


def test_outbox_claim_lease_serializes_workers_and_preserves_owner() -> None:
    """A held claim blocks a second worker and preserves the first owner."""

    repository = _outbox_repository()
    event = make_event()
    with repository.atomic():
        record = repository.enqueue(event, created_at=NOW, available_at=NOW)

    first_claimed = Event()
    release_first = Event()
    second_entered = Event()

    def _first_worker() -> _ClaimResult:
        close_old_connections()
        try:
            worker_repository = _outbox_repository()
            with worker_repository.atomic():
                claims = worker_repository.claim_due(worker_id="worker-one", as_of=LATER, limit=1)
                first_claimed.set()
                assert release_first.wait(timeout=10)
            return _ClaimResult(status="claimed", claim=claims[0])
        finally:
            connections["default"].close()

    def _second_worker() -> _ClaimResult:
        close_old_connections()
        try:
            second_entered.set()
            worker_repository = _outbox_repository()
            with worker_repository.atomic():
                claims = worker_repository.claim_due(worker_id="worker-two", as_of=LATER, limit=1)
            return _ClaimResult(
                status="claimed" if claims else "empty", claim=claims[0] if claims else None
            )
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(_first_worker)
        assert first_claimed.wait(timeout=10)
        second_future = executor.submit(_second_worker)
        assert second_entered.wait(timeout=10)
        assert not second_future.done()
        release_first.set()
        first_result = first_future.result(timeout=15)
        second_result = second_future.result(timeout=15)

    assert first_result.status == "claimed"
    assert first_result.claim is not None
    assert first_result.claim.worker_id == "worker-one"
    assert second_result.status == "empty"
    current = repository.get_exact(outbox_id=record.outbox_id)
    assert current is not None
    assert current.status == SystemAuditOutboxModel.STATUS_CLAIMED
    assert current.claimed_by == "worker-one"
    assert current.claim_token == first_result.claim.claim_token
    assert current.attempt_count == 1

    with repository.atomic():
        with pytest.raises(SystemAuditOutboxConflict, match="token"):
            repository.mark_delivered(
                outbox_id=record.outbox_id,
                worker_id="worker-two",
                claim_token="wrong-token",
                delivered_at=LATER,
            )


def test_outbox_claim_rollback_releases_lease_for_next_worker() -> None:
    """A rolled-back claim is not a lease: the next worker can claim once."""

    repository = _outbox_repository()
    event = make_event()
    with repository.atomic():
        record = repository.enqueue(event, created_at=NOW, available_at=NOW)

    first_claimed = Event()
    release_first = Event()
    second_entered = Event()

    def _rollback_worker() -> str:
        close_old_connections()
        try:
            worker_repository = _outbox_repository()
            try:
                with worker_repository.atomic():
                    worker_repository.claim_due(worker_id="worker-rollback", as_of=LATER, limit=1)
                    first_claimed.set()
                    assert release_first.wait(timeout=10)
                    raise RuntimeError("evidence rollback")
            except RuntimeError as error:
                return str(error)
            return "unexpected-commit"
        finally:
            connections["default"].close()

    def _reclaim_worker() -> _ClaimResult:
        close_old_connections()
        try:
            second_entered.set()
            worker_repository = _outbox_repository()
            with worker_repository.atomic():
                claims = worker_repository.claim_due(
                    worker_id="worker-reclaim", as_of=LATER, limit=1
                )
            return _ClaimResult(
                status="claimed" if claims else "empty", claim=claims[0] if claims else None
            )
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        rollback_future = executor.submit(_rollback_worker)
        assert first_claimed.wait(timeout=10)
        reclaim_future = executor.submit(_reclaim_worker)
        assert second_entered.wait(timeout=10)
        assert not reclaim_future.done()
        release_first.set()
        assert rollback_future.result(timeout=15) == "evidence rollback"
        reclaim_result = reclaim_future.result(timeout=15)

    assert reclaim_result.status == "claimed"
    assert reclaim_result.claim is not None
    assert reclaim_result.claim.worker_id == "worker-reclaim"
    assert reclaim_result.claim.attempt_count == 1
    current = repository.get_exact(outbox_id=record.outbox_id)
    assert current is not None
    assert current.status == SystemAuditOutboxModel.STATUS_CLAIMED
    assert current.claimed_by == "worker-reclaim"
    assert current.claim_token == reclaim_result.claim.claim_token
    assert current.attempt_count == 1


def test_postgresql_backlog_snapshot_is_closed_world_and_read_only() -> None:
    """PostgreSQL backlog observation aggregates every state without reclaiming rows."""

    repository = _outbox_repository()
    pending_event = _event(event_id="evt-pg-pending", idempotency_key="fetch:pg:pending")
    claimed_event = _event(event_id="evt-pg-claimed", idempotency_key="fetch:pg:claimed")
    failed_event = _event(event_id="evt-pg-failed", idempotency_key="fetch:pg:failed")
    delivered_event = _event(event_id="evt-pg-delivered", idempotency_key="fetch:pg:delivered")

    with repository.atomic():
        pending_record = repository.enqueue(
            pending_event,
            created_at=NOW + timedelta(seconds=4),
            available_at=NOW + timedelta(hours=1),
        )
        repository.enqueue(
            claimed_event,
            created_at=NOW + timedelta(seconds=1),
            available_at=NOW + timedelta(seconds=1),
        )
        failed_record = repository.enqueue(
            failed_event,
            created_at=NOW + timedelta(seconds=2),
            available_at=NOW + timedelta(seconds=2),
        )
        delivered_record = repository.enqueue(
            delivered_event,
            created_at=NOW + timedelta(seconds=3),
            available_at=NOW + timedelta(seconds=3),
        )

    with repository.atomic():
        claimed = repository.claim_due(worker_id="worker-pg-claimed", as_of=LATER, limit=1)[0]
        failed = repository.claim_due(worker_id="worker-pg-failed", as_of=LATER, limit=1)[0]
        repository.mark_failed(
            outbox_id=failed.outbox_id,
            worker_id=failed.worker_id,
            claim_token=failed.claim_token,
            error_code="publisher_error",
            failed_at=LATER,
        )
        delivered = repository.claim_due(worker_id="worker-pg-delivered", as_of=LATER, limit=1)[0]
        repository.mark_delivered(
            outbox_id=delivered.outbox_id,
            worker_id=delivered.worker_id,
            claim_token=delivered.claim_token,
            delivered_at=LATER,
        )

    observed_at = LATER + timedelta(minutes=5)
    snapshot = repository.get_backlog_snapshot(as_of=observed_at)

    assert snapshot.pending_count == 1
    assert snapshot.due_pending_count == 0
    assert snapshot.claimed_count == 1
    assert snapshot.expired_claimed_count == 1
    assert snapshot.failed_count == 1
    assert snapshot.delivered_count == 1
    assert snapshot.backlog_count == 2
    assert snapshot.oldest_backlog_at == NOW + timedelta(seconds=1)
    assert snapshot.oldest_claimed_at == LATER
    assert snapshot.oldest_backlog_age_seconds == pytest.approx(359.0)
    assert snapshot.oldest_claimed_age_seconds == pytest.approx(300.0)

    pending_restored = repository.get_exact(outbox_id=pending_record.outbox_id)
    assert pending_restored is not None
    assert pending_restored.status == SystemAuditOutboxModel.STATUS_PENDING
    claimed_restored = repository.get_exact(outbox_id=claimed.outbox_id)
    assert claimed_restored is not None
    assert claimed_restored.status == SystemAuditOutboxModel.STATUS_CLAIMED
    assert claimed_restored.claim_token == claimed.claim_token
    failed_restored = repository.get_exact(outbox_id=failed_record.outbox_id)
    assert failed_restored is not None
    assert failed_restored.status == SystemAuditOutboxModel.STATUS_FAILED
    delivered_restored = repository.get_exact(outbox_id=delivered_record.outbox_id)
    assert delivered_restored is not None
    assert delivered_restored.status == SystemAuditOutboxModel.STATUS_DELIVERED
