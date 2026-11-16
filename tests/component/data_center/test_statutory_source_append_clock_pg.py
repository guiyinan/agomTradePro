"""Unexecuted two-connection PG contract source for append clock ordering."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from django.db import connection, connections, transaction

from apps.data_center.domain.statutory_source_documents import (
    RetainedStatutorySourceDocumentCapture,
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentRevision,
)
from apps.data_center.infrastructure.statutory_source_body_store import StatutorySourceBodyStore
from apps.data_center.infrastructure.statutory_source_models import (
    StatutorySourceDocumentCaptureModel,
    StatutorySourceDocumentRevisionModel,
)
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(available_apps=["apps.data_center"])
_BODY = b"Synthetic-only source clock lock-wait body"


def _revision(document_id: str) -> StatutorySourceDocumentRevision:
    """Build one synthetic source revision for the isolated native schema."""

    return StatutorySourceDocumentRevision(
        issuer="Synthetic clock-lock publisher",
        document_id=document_id,
        source_version="1",
        canonical_url="https://example.invalid/source-clock-lock",
        title="Synthetic source clock lock test",
        legal_number="CLOCK-LOCK-1",
        publication_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=date(2001, 1, 1),
        ),
        effective_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.UNKNOWN,
        ),
        body_sha256=sha256(_BODY).hexdigest(),
        body_size_bytes=len(_BODY),
    )


def _wait_for_revision_writer(pid: int) -> bool:
    """Wait briefly until PostgreSQL reports a writer waiting on the revision table."""

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                      FROM pg_locks
                     WHERE pid = %s
                       AND locktype = 'relation'
                       AND relation = to_regclass('public.dc_statutory_source_revision')::oid
                       AND mode = 'ShareRowExclusiveLock'
                       AND NOT granted
                )
                """,
                [pid],
            )
            row = cursor.fetchone()
        if row is not None and row[0] is True:
            return True
        time.sleep(0.01)
    return False


@pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])
def test_postgres_append_capture_clock_follows_body_and_fixed_table_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove exact append time follows body verification and revision→capture locks."""

    if connection.vendor != "postgresql":
        pytest.skip("Native PostgreSQL source-clock lock contract")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM django_migrations WHERE app=%s AND name=%s",
            ["data_center", "0111_statutory_source_evidence"],
        )
        assert cursor.fetchone() == (1,)
        cursor.execute(
            "SELECT to_regclass('public.dc_statutory_source_revision')::oid, "
            "to_regclass('public.dc_statutory_source_capture')::oid"
        )
        source_tables = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgenabled='A' AND NOT tgisinternal "
            "AND tgname IN (%s,%s)",
            ["dc_stat_rev_immutable", "dc_stat_cap_immutable"],
        )
        trigger_row = cursor.fetchone()
    assert source_tables is not None and all(source_tables)
    assert trigger_row == (2,)

    capture_id = uuid4()
    revision = _revision(f"clock-lock-{uuid4().hex}")
    body_store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
    body_reference = body_store.store(capture_id, _BODY)
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        row = cursor.fetchone()
    assert row is not None
    capture = RetainedStatutorySourceDocumentCapture(
        capture_id=capture_id,
        revision=revision,
        captured_at=row[0] - timedelta(seconds=1),
        content_type="text/html",
        body_reference=body_reference,
    )
    body_verified = threading.Event()
    clock_sampled = threading.Event()

    def server_clock() -> datetime:
        """Expose the sampling point while returning real PostgreSQL wall time."""

        clock_sampled.set()
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            clock_row = cursor.fetchone()
        assert clock_row is not None
        return clock_row[0]

    repository = DjangoStatutorySourceRepository(
        body_store=body_store,
        using="default",
        clock=server_clock,
    )
    verify_body = repository._verify_body

    def verify_then_signal(value: RetainedStatutorySourceDocumentCapture) -> None:
        """Record that retained bytes passed exact integrity checks."""

        verify_body(value)
        body_verified.set()

    monkeypatch.setattr(repository, "_verify_body", verify_then_signal)
    worker_pid: list[int] = []
    worker_started = threading.Event()
    worker_errors: list[Exception] = []

    def writer() -> None:
        """Append on a second database connection while a PIT reader fence is held."""

        worker_connection = connections["default"]
        try:
            worker_connection.ensure_connection()
            with worker_connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pid_row = cursor.fetchone()
            assert pid_row is not None
            worker_pid.append(pid_row[0])
            worker_started.set()
            repository.append_capture(revision, capture)
        except Exception as error:
            worker_errors.append(error)
        finally:
            worker_connection.close()

    thread = threading.Thread(target=writer, daemon=True)
    lock_release_at: datetime | None = None
    try:
        with transaction.atomic(using="default"):
            with connection.cursor() as cursor:
                cursor.execute("LOCK TABLE public.dc_statutory_source_revision IN SHARE MODE")
                cursor.execute("LOCK TABLE public.dc_statutory_source_capture IN SHARE MODE")
            thread.start()
            assert worker_started.wait(timeout=5.0)
            assert worker_pid
            assert _wait_for_revision_writer(worker_pid[0])
            assert body_verified.is_set()
            assert not clock_sampled.is_set()
            with connection.cursor() as cursor:
                cursor.execute("SELECT clock_timestamp()")
                release_row = cursor.fetchone()
            assert release_row is not None
            lock_release_at = release_row[0]
    finally:
        if thread.ident is not None:
            thread.join(timeout=10.0)

    assert not thread.is_alive()
    assert not worker_errors
    assert clock_sampled.is_set()
    assert lock_release_at is not None
    revision_row = StatutorySourceDocumentRevisionModel.objects.get(
        issuer=revision.issuer,
        document_id=revision.document_id,
        source_version=revision.source_version,
    )
    capture_row = StatutorySourceDocumentCaptureModel.objects.get(capture_id=capture_id)
    assert revision_row.recorded_at >= lock_release_at
    assert capture_row.recorded_at >= lock_release_at


@pytest.fixture(autouse=True)
def _require_owned_native_test_database(
    django_db_use_migrations: bool,
    transactional_db: None,
) -> None:
    """Require full migrations and the explicit isolated PostgreSQL TEST.NAME."""

    if connection.vendor != "postgresql" or not django_db_use_migrations:
        pytest.skip("native financial availability contracts require migrated PostgreSQL")
    assert_native_postgres_test_database()
