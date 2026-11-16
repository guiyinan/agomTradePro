"""Native PostgreSQL contracts for the financial numeric catalog.

This suite requires an explicitly isolated TEST.NAME database, applied
migrations, real Django
authentication, the actual egress-audit table, and the actual retained-body
store. Its source document, metric and context are synthetic test data; it does
not qualify or seed a production metric.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

import pytest
from django.apps import apps
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.models import Model
from django.utils import timezone

from apps.data_center.domain.financial_numeric_catalog import (
    FinancialNumericCatalogResolutionPurpose,
)
from apps.data_center.domain.financial_numeric_evidence import FinancialMetricSourceContract
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceContextRequirement,
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.provider_document_response import (
    PUBLIC_DOCUMENT_SOURCE_TYPE,
    ProviderDocumentResponseCapture,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.statutory_source_documents import StatutorySourceBodyReference
from apps.data_center.infrastructure.egress_models import EgressRequestAuditModel
from apps.data_center.infrastructure.financial_numeric_catalog_capture_repository import (
    DjangoFinancialNumericSourceCaptureRepository,
    FinancialNumericCatalogEvidenceError,
)
from apps.data_center.infrastructure.financial_numeric_catalog_models import (
    FinancialMetricSourceCatalogEntryModel,
    FinancialMetricSourceCatalogOwnerEventModel,
    FinancialNumericSourceDocumentCaptureModel,
)
from apps.data_center.infrastructure.financial_numeric_catalog_repository import (
    DjangoFinancialMetricSourceCatalogRepository,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_PROVIDER_NAME,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.statutory_source_body_store import (
    StatutorySourceBodyStore,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

_OWNER_PASSWORD = "native-numeric-catalog-test-password"
_DOC_URL = "https://docs.example.test/financial-fields"
_DOC_HOST = "docs.example.test"
_DOC_DATASET = "synthetic.financial.documentation"
_DEPLOYMENT_REGION = "isolated-test-region"
_SOURCE_CONTEXT = {"synthetic_statement_scope": "single-period"}


class _CountingBodyStore:
    """Count real body-store reads while delegating every byte operation."""

    def __init__(self, delegate: StatutorySourceBodyStore) -> None:
        """Wrap one actual private-root body store."""

        self._delegate = delegate
        self.read_count = 0

    def store(self, capture_id: UUID, body: bytes) -> StatutorySourceBodyReference:
        """Persist bytes through the real protected file store."""

        return self._delegate.store(capture_id, body)

    def read(self, reference: StatutorySourceBodyReference) -> bytes:
        """Read exact bytes through the real store and count the repository call."""

        self.read_count += 1
        return self._delegate.read(reference)


class _Clock:
    """Explicit mutable UTC clock used to exercise catalog knowledge cutoffs."""

    def __init__(self, value: datetime) -> None:
        """Bind one aware UTC clock value."""

        self.value = value

    def __call__(self) -> datetime:
        """Return the current deterministic catalog clock sample."""

        return self.value


class _RecordingClock:
    """Return an injected event instant and retain the real time it was sampled."""

    def __init__(self, value: datetime) -> None:
        """Bind one deterministic UTC event time."""

        self.value = value
        self.sampled_at: list[datetime] = []

    def __call__(self) -> datetime:
        """Record that the repository sampled its clock after obtaining row locks."""

        self.sampled_at.append(timezone.now().astimezone(UTC))
        return self.value


class _ExecuteQuery(Protocol):
    """Django connection execute callable used by a thread-local query wrapper."""

    def __call__(
        self,
        sql: str,
        params: object,
        many: bool,
        context: object,
    ) -> object:
        """Execute one database statement through Django's existing wrapper chain."""
        ...


@pytest.fixture
def native_postgres_database(django_db_use_migrations: bool) -> None:
    """Require the project's named isolated PostgreSQL TEST database and migrations."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip("financial numeric catalog contracts require migrated isolated PostgreSQL")
    assert_native_postgres_test_database()


@pytest.fixture
def counting_body_store(tmp_path: Path) -> _CountingBodyStore:
    """Create a real bounded private-root body store with a read-counter wrapper."""

    actual_store = StatutorySourceBodyStore(
        tmp_path / "retained-source-bodies", max_body_bytes=4096
    )
    return _CountingBodyStore(actual_store)


def _provider() -> ProviderConfigModel:
    """Persist one exact public-document provider identity for FK and drift checks."""

    return ProviderConfigModel.objects.create(
        name=f"numeric-catalog-doc-{uuid4().hex}",
        source_type=PUBLIC_DOCUMENT_SOURCE_TYPE,
        is_active=True,
        priority=50,
    )


def _capture(
    *,
    body_store: _CountingBodyStore,
    response_completed_at: datetime | None = None,
    create_audit: bool = True,
) -> tuple[
    FinancialNumericSourceDocumentCaptureReference,
    ProviderConfigModel,
    bytes,
    datetime,
]:
    """Persist one synthetic response with its real successful audit and retained bytes."""

    provider = _provider()
    capture_id = uuid4()
    body = b"<html><table><tr><td>SYNTHETIC_NATIVE_FIELD</td><td>7.125</td></tr></table></html>"
    body_hash = hashlib.sha256(body).hexdigest()
    response_at = response_completed_at or (timezone.now() - timedelta(seconds=10))
    response = ProviderDocumentResponseCapture(
        request_id=capture_id,
        attempt=1,
        egress_id=37,
        target_url_sha256=hashlib.sha256(_DOC_URL.encode("utf-8")).hexdigest(),
        target_host=_DOC_HOST,
        body=body,
        body_sha256=body_hash,
        body_size_bytes=len(body),
        response_completed_at=response_at.astimezone(UTC),
        status_code=200,
        content_type="text/html; charset=utf-8",
        transport=ProviderResponseTransport.EGRESS,
    )
    if create_audit:
        EgressRequestAuditModel.objects.create(
            request_id=capture_id,
            provider_id=provider.pk,
            dataset_key=_DOC_DATASET,
            target_host=_DOC_HOST,
            deployment_region=_DEPLOYMENT_REGION,
            egress_id=response.egress_id,
            attempt=response.attempt,
            outcome="success",
        )
    recorded_at = timezone.now().astimezone(UTC) + timedelta(milliseconds=1)
    reference = FinancialNumericSourceDocumentCaptureReference(
        capture_id=capture_id,
        document_id="synthetic-financial-document",
        issuer="synthetic-document-publisher",
        canonical_url=_DOC_URL,
        body_sha256=body_hash,
        body_size_bytes=len(body),
        captured_at=response.response_completed_at,
        content_type=response.content_type,
    )
    repository = DjangoFinancialNumericSourceCaptureRepository(
        body_store=body_store,
        using="default",
        clock=lambda: recorded_at,
    )
    persisted_reference = repository.append_document_capture(
        provider_id=provider.pk,
        dataset_key=_DOC_DATASET,
        deployment_region=_DEPLOYMENT_REGION,
        reference=reference,
        response=response,
    )
    assert persisted_reference == reference
    return reference, provider, body, recorded_at


def _qualification(
    reference: FinancialNumericSourceDocumentCaptureReference,
) -> FinancialNumericSourceQualification:
    """Build an explicit synthetic contract and source-context qualification."""

    contract = FinancialMetricSourceContract(
        provider=AKSHARE_PROVIDER_NAME,
        dataset_key="equity.financial.fact",
        metric_code="SYNTHETIC_NATIVE_METRIC",
        source_field="SYNTHETIC_NATIVE_FIELD",
        source_unit="synthetic-unit",
        canonical_unit="synthetic-unit",
        scale_numerator=1,
        scale_denominator=1,
        contract_version="test.v1",
        origin="native",
    )
    return FinancialNumericSourceQualification(
        contract=contract,
        endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
        source_applicability="synthetic test document only",
        document_capture=reference,
        context_requirements=(
            FinancialNumericSourceContextRequirement(
                "synthetic_statement_scope",
                "single-period",
            ),
        ),
        effective_from=reference.captured_at,
        effective_until=None,
    )


def _catalog_repository(
    *,
    body_store: _CountingBodyStore,
    clock: _Clock,
    using: str = "default",
) -> DjangoFinancialMetricSourceCatalogRepository:
    """Construct both real persistence adapters against one explicit alias."""

    capture_repository = DjangoFinancialNumericSourceCaptureRepository(
        body_store=body_store,
        using=using,
        clock=clock,
    )
    return DjangoFinancialMetricSourceCatalogRepository(
        capture_repository=capture_repository,
        using=using,
        clock=clock,
    )


def _authenticate_owner(monkeypatch: pytest.MonkeyPatch, user: object) -> object:
    """Authenticate an actual persisted account through the production command backend."""

    from apps.data_center.management.commands import manage_financial_numeric_catalog

    password = _OWNER_PASSWORD
    monkeypatch.setattr(manage_financial_numeric_catalog, "getpass", lambda _prompt: password)
    command = manage_financial_numeric_catalog.Command()
    username = user.get_username()  # type: ignore[attr-defined]
    authenticated = command._authenticate_owner(username)
    assert authenticated.pk == user.pk  # type: ignore[attr-defined]
    return authenticated


def _assert_pg_append_only(model: type[Model], pk: object) -> None:
    """Prove migration triggers reject raw PostgreSQL update and delete operations."""

    table = connection.ops.quote_name(model._meta.db_table)
    pk_column = connection.ops.quote_name(model._meta.pk.column)
    recorded_column = connection.ops.quote_name("recorded_at")
    for sql in (
        f"UPDATE {table} SET {recorded_column} = {recorded_column} WHERE {pk_column} = %s",
        f"DELETE FROM {table} WHERE {pk_column} = %s",
    ):
        with pytest.raises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, [pk])


def test_catalog_models_are_registered_and_exported_by_the_public_facade(
    native_postgres_database: None,
) -> None:
    """Confirm all new ORM classes have one registered identity and intended tables."""

    from apps.data_center import models as public_models

    assert apps.get_model("data_center", "FinancialNumericSourceDocumentCaptureModel") is (
        FinancialNumericSourceDocumentCaptureModel
    )
    assert apps.get_model("data_center", "FinancialMetricSourceCatalogEntryModel") is (
        FinancialMetricSourceCatalogEntryModel
    )
    assert apps.get_model("data_center", "FinancialMetricSourceCatalogOwnerEventModel") is (
        FinancialMetricSourceCatalogOwnerEventModel
    )
    assert public_models.FinancialNumericSourceDocumentCaptureModel is (
        FinancialNumericSourceDocumentCaptureModel
    )
    assert public_models.FinancialMetricSourceCatalogEntryModel is (
        FinancialMetricSourceCatalogEntryModel
    )
    assert public_models.FinancialMetricSourceCatalogOwnerEventModel is (
        FinancialMetricSourceCatalogOwnerEventModel
    )
    assert FinancialNumericSourceDocumentCaptureModel._meta.db_table == (
        "data_center_fin_numeric_doc_capture"
    )
    assert FinancialMetricSourceCatalogEntryModel._meta.db_table == (
        "data_center_fin_metric_source_entry"
    )
    assert FinancialMetricSourceCatalogOwnerEventModel._meta.db_table == (
        "data_center_fin_metric_source_owner_event"
    )


def test_reverse_migration_waits_for_capture_writer_then_refuses_committed_row(
    native_postgres_database: None,
    counting_body_store: _CountingBodyStore,
) -> None:
    """Keep a concurrent committed capture visible to the real reverse migration guard."""

    from django.db.migrations.executor import MigrationExecutor

    lock_requested = threading.Event()
    migration_finished = threading.Event()
    lock_statements: list[str] = []
    migration_errors: list[Exception] = []

    def reverse_catalog_migration() -> None:
        """Reverse 0116 on a second PostgreSQL connection and retain its outcome."""

        database = connections["default"]
        database.close()

        def observe_catalog_lock(
            execute: _ExecuteQuery,
            sql: str,
            params: object,
            many: bool,
            context: object,
        ) -> object:
            """Signal before blocking on all three table locks."""

            upper_sql = sql.upper()
            expected_tables = (
                "DATA_CENTER_FIN_NUMERIC_DOC_CAPTURE",
                "DATA_CENTER_FIN_METRIC_SOURCE_ENTRY",
                "DATA_CENTER_FIN_METRIC_SOURCE_OWNER_EVENT",
            )
            if "LOCK TABLE" in upper_sql and all(
                table_name in upper_sql for table_name in expected_tables
            ):
                lock_statements.append(sql)
                lock_requested.set()
            elif (
                "SELECT 1" in upper_sql
                and "DATA_CENTER_FIN_NUMERIC_DOC_CAPTURE" in upper_sql
                and not lock_requested.is_set()
            ):
                raise AssertionError("reverse guard checked rows before locking catalog tables")
            return execute(sql, params, many, context)

        try:
            with database.execute_wrapper(observe_catalog_lock):
                MigrationExecutor(database).migrate(
                    [("data_center", "0115_calendar_history_catalog_immutability")]
                )
        except Exception as error:
            migration_errors.append(error)
        finally:
            migration_finished.set()
            database.close()

    migration_thread = threading.Thread(
        target=reverse_catalog_migration,
        name="numeric-catalog-reverse-migration",
    )
    lock_was_requested = False
    migration_finished_before_writer_release = False
    try:
        with transaction.atomic(using="default"):
            reference, _provider, _body, _recorded_at = _capture(body_store=counting_body_store)
            migration_thread.start()
            lock_was_requested = lock_requested.wait(timeout=10)
            migration_finished_before_writer_release = migration_finished.wait(timeout=0.2)
    finally:
        if migration_thread.ident is not None:
            migration_thread.join(timeout=10)

    assert not migration_thread.is_alive()
    assert lock_was_requested
    assert not migration_finished_before_writer_release
    assert len(lock_statements) == 1
    lock_sql = lock_statements[0].upper()
    assert "ACCESS EXCLUSIVE" in lock_sql
    expected_order = (
        "DATA_CENTER_FIN_NUMERIC_DOC_CAPTURE",
        "DATA_CENTER_FIN_METRIC_SOURCE_ENTRY",
        "DATA_CENTER_FIN_METRIC_SOURCE_OWNER_EVENT",
    )
    lock_positions = tuple(lock_sql.index(table_name) for table_name in expected_order)
    assert lock_positions == tuple(sorted(lock_positions))
    assert len(migration_errors) == 1
    assert isinstance(migration_errors[0], IrreversibleError)
    assert FinancialNumericSourceDocumentCaptureModel.objects.filter(
        capture_id=reference.capture_id
    ).exists()


def test_owner_auth_apply_revoke_pit_and_append_only_guards_use_real_rows(
    native_postgres_database: None,
    monkeypatch: pytest.MonkeyPatch,
    counting_body_store: _CountingBodyStore,
) -> None:
    """Bind real auth/FKs, preserve PIT, and reject ORM and raw-SQL evidence edits."""

    reference, _provider_row, body, capture_recorded_at = _capture(body_store=counting_body_store)
    qualification = _qualification(reference)
    user_model = get_user_model()
    username = f"numeric-catalog-owner-{uuid4().hex}"
    user = user_model.objects.create_user(
        username=username,
        password=_OWNER_PASSWORD,
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )
    authenticated = _authenticate_owner(monkeypatch, user)
    assert (
        authenticate(
            request=None,
            **{user_model.USERNAME_FIELD: username, "password": _OWNER_PASSWORD},
        )
        is not None
    )

    apply_at = capture_recorded_at + timedelta(seconds=2)
    clock = _Clock(apply_at)
    repository = _catalog_repository(body_store=counting_body_store, clock=clock)
    entry_id = repository.append_qualification(
        qualification,
        actor_id=authenticated.pk,
        actor_username=authenticated.get_username(),
    )
    entry = FinancialMetricSourceCatalogEntryModel.objects.get(pk=entry_id)
    apply_event = FinancialMetricSourceCatalogOwnerEventModel.objects.get(
        entry_id=entry_id,
        action="apply",
    )
    assert apply_event.actor_id == user.pk
    assert apply_event.actor_username_snapshot == username
    assert entry.document_capture.body_sha256 == reference.body_sha256
    assert entry.document_capture.content_type == "text/html; charset=utf-8"
    assert entry.document_capture.body_size_bytes == len(body)

    counting_body_store.read_count = 0
    capture_reader = DjangoFinancialNumericSourceCaptureRepository(
        body_store=counting_body_store,
        using="default",
        clock=clock,
    )
    retained = capture_reader.read_verified_capture(reference, known_at=apply_at)
    assert retained.body == body
    assert counting_body_store.read_count == 1

    source_response_at = reference.captured_at
    assert (
        repository.resolve_exact(
            qualification.contract.identity,
            endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
            source_response_completed_at=source_response_at,
            source_context=_SOURCE_CONTEXT,
            known_at=apply_at + timedelta(seconds=1),
        )
        == qualification
    )
    with transaction.atomic(using="default"):
        assert (
            repository.resolve_exact_in_uow(
                qualification.contract.identity,
                endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
                source_response_completed_at=source_response_at,
                source_context=_SOURCE_CONTEXT,
                purpose=FinancialNumericCatalogResolutionPurpose.CURRENT_WRITE,
                known_at=apply_at + timedelta(seconds=1),
            )
            == qualification
        )

    with pytest.raises(ValidationError):
        entry.save()
    with pytest.raises(ValidationError):
        FinancialMetricSourceCatalogEntryModel.objects.filter(pk=entry_id).update(
            qualification_sha256="0" * 64
        )

    clock.value = apply_at - timedelta(seconds=1)
    with pytest.raises(FinancialNumericCatalogEvidenceError):
        repository.append_revocation(
            entry_id,
            expected_qualification_identity=qualification.identity,
            expected_qualification_sha256=qualification.content_hash,
            actor_id=authenticated.pk,
            actor_username=authenticated.get_username(),
        )
    assert (
        FinancialMetricSourceCatalogOwnerEventModel.objects.filter(entry_id=entry_id).count() == 1
    )

    revoke_at = apply_at + timedelta(seconds=3)
    clock.value = revoke_at
    repository.append_revocation(
        entry_id,
        expected_qualification_identity=qualification.identity,
        expected_qualification_sha256=qualification.content_hash,
        actor_id=authenticated.pk,
        actor_username=authenticated.get_username(),
    )
    row_after_revoke = FinancialMetricSourceCatalogEntryModel.objects.get(pk=entry_id)
    assert row_after_revoke.qualification == entry.qualification
    assert row_after_revoke.recorded_at == entry.recorded_at
    assert (
        repository.resolve_exact(
            qualification.contract.identity,
            endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
            source_response_completed_at=source_response_at,
            source_context=_SOURCE_CONTEXT,
            known_at=apply_at + timedelta(seconds=1),
        )
        == qualification
    )
    assert (
        repository.resolve_exact(
            qualification.contract.identity,
            endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
            source_response_completed_at=source_response_at,
            source_context=_SOURCE_CONTEXT,
            known_at=revoke_at + timedelta(seconds=1),
        )
        is None
    )
    with transaction.atomic(using="default"):
        assert (
            repository.resolve_exact_in_uow(
                qualification.contract.identity,
                endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
                source_response_completed_at=source_response_at,
                source_context=_SOURCE_CONTEXT,
                purpose=FinancialNumericCatalogResolutionPurpose.POINT_IN_TIME_READ,
                known_at=apply_at + timedelta(seconds=1),
            )
            == qualification
        )
    with transaction.atomic(using="default"):
        assert (
            repository.resolve_exact_in_uow(
                qualification.contract.identity,
                endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
                source_response_completed_at=source_response_at,
                source_context=_SOURCE_CONTEXT,
                purpose=FinancialNumericCatalogResolutionPurpose.CURRENT_READ,
                known_at=apply_at + timedelta(seconds=1),
            )
            is None
        )
        assert (
            repository.resolve_exact_in_uow(
                qualification.contract.identity,
                endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
                source_response_completed_at=source_response_at,
                source_context=_SOURCE_CONTEXT,
                purpose=FinancialNumericCatalogResolutionPurpose.CURRENT_PUBLICATION,
                known_at=revoke_at + timedelta(seconds=1),
            )
            is None
        )

    with pytest.raises(FinancialNumericCatalogEvidenceError):
        repository.append_qualification(
            qualification,
            actor_id=authenticated.pk,
            actor_username=authenticated.get_username(),
        )
    with pytest.raises(FinancialNumericCatalogEvidenceError):
        repository.append_revocation(
            entry_id,
            expected_qualification_identity=qualification.identity,
            expected_qualification_sha256=qualification.content_hash,
            actor_id=authenticated.pk,
            actor_username=authenticated.get_username(),
        )
    assert (
        FinancialMetricSourceCatalogOwnerEventModel.objects.filter(entry_id=entry_id).count() == 2
    )

    capture = FinancialNumericSourceDocumentCaptureModel.objects.get(pk=reference.capture_id)
    event = FinancialMetricSourceCatalogOwnerEventModel.objects.get(
        entry_id=entry_id, action="apply"
    )
    _assert_pg_append_only(FinancialNumericSourceDocumentCaptureModel, capture.pk)
    _assert_pg_append_only(FinancialMetricSourceCatalogEntryModel, entry.pk)
    _assert_pg_append_only(FinancialMetricSourceCatalogOwnerEventModel, event.pk)
    migration_module = import_module("apps.data_center.migrations.0116_financial_numeric_catalog")
    with connection.schema_editor() as schema_editor:
        with pytest.raises(IrreversibleError, match="rows exist"):
            migration_module.allow_reverse_when_empty(apps, schema_editor)


def test_revocation_waits_for_current_uow_and_samples_event_clock_after_entry_lock(
    native_postgres_database: None,
    monkeypatch: pytest.MonkeyPatch,
    counting_body_store: _CountingBodyStore,
) -> None:
    """A current writer fence and revocation serialize on the same entry row."""

    reference, _provider_row, _body, capture_recorded_at = _capture(body_store=counting_body_store)
    qualification = _qualification(reference)
    user_model = get_user_model()
    username = f"numeric-catalog-lock-owner-{uuid4().hex}"
    user = user_model.objects.create_user(
        username=username,
        password=_OWNER_PASSWORD,
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )
    authenticated = _authenticate_owner(monkeypatch, user)
    apply_at = capture_recorded_at + timedelta(seconds=2)
    apply_repository = _catalog_repository(
        body_store=counting_body_store,
        clock=_Clock(apply_at),
    )
    entry_id = apply_repository.append_qualification(
        qualification,
        actor_id=authenticated.pk,
        actor_username=authenticated.get_username(),
    )

    cutoff = apply_at + timedelta(seconds=1)
    revoke_at = apply_at + timedelta(seconds=2)
    revocation_clock = _RecordingClock(revoke_at)
    current_repository = _catalog_repository(
        body_store=counting_body_store,
        clock=_Clock(revoke_at + timedelta(seconds=1)),
    )
    revoke_repository = _catalog_repository(
        body_store=counting_body_store,
        clock=revocation_clock,
    )
    current_read_locked = threading.Event()
    release_current_read = threading.Event()
    revoke_entry_lock_statement = threading.Event()
    revoke_completed = threading.Event()
    result_holder: list[FinancialNumericSourceQualification | None] = []
    writer_release_times: list[datetime] = []
    failures: list[Exception] = []

    def current_writer() -> None:
        """Hold the current-use entry lock until the outer write transaction commits."""

        database = connections["default"]
        database.close()
        try:
            with transaction.atomic(using="default"):
                resolved = current_repository.resolve_exact_in_uow(
                    qualification.contract.identity,
                    endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
                    source_response_completed_at=reference.captured_at,
                    source_context=_SOURCE_CONTEXT,
                    purpose=FinancialNumericCatalogResolutionPurpose.CURRENT_WRITE,
                    known_at=cutoff,
                )
                result_holder.append(resolved)
                current_read_locked.set()
                if not release_current_read.wait(timeout=10):
                    raise TimeoutError("current UOW lock holder did not receive release")
                writer_release_times.append(timezone.now().astimezone(UTC))
        except Exception as error:
            failures.append(error)
        finally:
            database.close()

    def revoker() -> None:
        """Attempt the real authenticated revoke from an independent PostgreSQL connection."""

        database = connections["default"]
        database.close()

        def observe_entry_lock(
            execute: _ExecuteQuery,
            sql: str,
            params: object,
            many: bool,
            context: object,
        ) -> object:
            """Signal when the real SELECT FOR UPDATE reaches the entry row."""

            if "FOR UPDATE" in sql.upper() and "data_center_fin_metric_source_entry" in sql:
                revoke_entry_lock_statement.set()
            return execute(sql, params, many, context)

        try:
            with database.execute_wrapper(observe_entry_lock):
                revoke_repository.append_revocation(
                    entry_id,
                    expected_qualification_identity=qualification.identity,
                    expected_qualification_sha256=qualification.content_hash,
                    actor_id=authenticated.pk,
                    actor_username=authenticated.get_username(),
                )
        except Exception as error:
            failures.append(error)
        finally:
            revoke_completed.set()
            database.close()

    writer_thread = threading.Thread(target=current_writer, name="numeric-current-writer")
    revoke_thread = threading.Thread(target=revoker, name="numeric-owner-revoker")
    revoke_thread_started = False
    writer_thread.start()
    try:
        assert current_read_locked.wait(timeout=10)
        assert result_holder == [qualification]
        revoke_thread.start()
        revoke_thread_started = True
        assert revoke_entry_lock_statement.wait(timeout=10)
        assert revocation_clock.sampled_at == []
        assert not revoke_completed.wait(timeout=0.2)
    finally:
        release_time = timezone.now().astimezone(UTC)
        release_current_read.set()
    writer_thread.join(timeout=10)
    if revoke_thread_started:
        revoke_thread.join(timeout=10)

    assert not writer_thread.is_alive()
    assert revoke_thread_started
    assert not revoke_thread.is_alive()
    assert failures == []
    assert revoke_completed.is_set()
    assert len(revocation_clock.sampled_at) == 1
    assert writer_release_times
    assert revocation_clock.sampled_at[0] >= release_time
    revoke_event = FinancialMetricSourceCatalogOwnerEventModel.objects.get(
        entry_id=entry_id,
        action="revoke",
    )
    assert revoke_event.event_at == revoke_at
    assert revoke_event.recorded_at == revoke_at

    with transaction.atomic(using="default"):
        assert (
            current_repository.resolve_exact_in_uow(
                qualification.contract.identity,
                endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
                source_response_completed_at=reference.captured_at,
                source_context=_SOURCE_CONTEXT,
                purpose=FinancialNumericCatalogResolutionPurpose.POINT_IN_TIME_READ,
                known_at=cutoff,
            )
            == qualification
        )
    with transaction.atomic(using="default"):
        assert (
            current_repository.resolve_exact_in_uow(
                qualification.contract.identity,
                endpoint=AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
                source_response_completed_at=reference.captured_at,
                source_context=_SOURCE_CONTEXT,
                purpose=FinancialNumericCatalogResolutionPurpose.CURRENT_WRITE,
                known_at=cutoff,
            )
            is None
        )


def test_authentication_and_database_actor_check_reject_wrong_or_inactive_users(
    native_postgres_database: None,
    monkeypatch: pytest.MonkeyPatch,
    counting_body_store: _CountingBodyStore,
) -> None:
    """Real login and transactional recheck require the exact active superuser."""

    from apps.data_center.management.commands import manage_financial_numeric_catalog

    reference, _provider_row, _body, capture_recorded_at = _capture(body_store=counting_body_store)
    qualification = _qualification(reference)
    user_model = get_user_model()
    owner_name = f"numeric-catalog-owner-{uuid4().hex}"
    owner = user_model.objects.create_user(
        username=owner_name,
        password=_OWNER_PASSWORD,
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )
    clock = _Clock(capture_recorded_at + timedelta(seconds=2))
    repository = _catalog_repository(body_store=counting_body_store, clock=clock)

    monkeypatch.setattr(
        manage_financial_numeric_catalog, "getpass", lambda _prompt: "wrong-password"
    )
    with pytest.raises(CommandError):
        manage_financial_numeric_catalog.Command()._authenticate_owner(owner_name)

    monkeypatch.setattr(
        manage_financial_numeric_catalog, "getpass", lambda _prompt: _OWNER_PASSWORD
    )
    authenticated = manage_financial_numeric_catalog.Command()._authenticate_owner(owner_name)
    owner.is_active = False
    owner.save(update_fields=["is_active"])
    with pytest.raises(FinancialNumericCatalogEvidenceError):
        repository.append_qualification(
            qualification,
            actor_id=authenticated.pk,
            actor_username=authenticated.get_username(),
        )
    assert FinancialMetricSourceCatalogEntryModel.objects.count() == 0
    assert FinancialMetricSourceCatalogOwnerEventModel.objects.count() == 0

    owner.is_active = True
    owner.save(update_fields=["is_active"])
    ordinary_name = f"numeric-catalog-ordinary-{uuid4().hex}"
    ordinary = user_model.objects.create_user(
        username=ordinary_name,
        password=_OWNER_PASSWORD,
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    with pytest.raises(CommandError):
        manage_financial_numeric_catalog.Command()._authenticate_owner(ordinary_name)
    with pytest.raises(FinancialNumericCatalogEvidenceError):
        repository.append_qualification(
            qualification,
            actor_id=owner.pk,
            actor_username=ordinary.get_username(),
        )
    assert FinancialMetricSourceCatalogEntryModel.objects.count() == 0


def test_catalog_capture_requires_exact_audit_and_preserves_provider_identity_history(
    native_postgres_database: None,
    tmp_path: Path,
    counting_body_store: _CountingBodyStore,
) -> None:
    """Capture verification reads actual bytes and binds the exact audit/provider identity."""

    reference, provider, body, recorded_at = _capture(body_store=counting_body_store)
    capture_reader = DjangoFinancialNumericSourceCaptureRepository(
        body_store=counting_body_store,
        using="default",
        clock=lambda: recorded_at + timedelta(seconds=5),
    )
    provider.is_active = False
    provider.save(update_fields=["is_active"])
    counting_body_store.read_count = 0
    retained = capture_reader.read_verified_capture(
        reference,
        known_at=recorded_at + timedelta(seconds=5),
    )
    assert retained.body == body
    assert retained.reference.content_type == "text/html; charset=utf-8"
    assert counting_body_store.read_count == 1

    provider.name = f"renamed-{provider.name}"
    provider.save(update_fields=["name"])
    with pytest.raises(FinancialNumericCatalogEvidenceError):
        capture_reader.read_verified_capture(
            reference,
            known_at=recorded_at + timedelta(seconds=6),
        )

    no_audit_store = StatutorySourceBodyStore(
        tmp_path / "missing-audit-bodies", max_body_bytes=4096
    )
    with pytest.raises(FinancialNumericCatalogEvidenceError):
        _capture(body_store=_CountingBodyStore(no_audit_store), create_audit=False)


def test_catalog_repositories_require_one_database_alias(
    native_postgres_database: None,
    counting_body_store: _CountingBodyStore,
) -> None:
    """Reject adapter pairs that could split capture and Owner rows across databases."""

    capture_repository = DjangoFinancialNumericSourceCaptureRepository(
        body_store=counting_body_store,
        using="default",
    )
    assert capture_repository.database_alias == "default"
    with pytest.raises(ValueError, match="share one database alias"):
        DjangoFinancialMetricSourceCatalogRepository(
            capture_repository=capture_repository,
            using="numeric-catalog-other",
        )


def test_management_command_rejects_nondefault_database_before_auth_http_or_writes(
    native_postgres_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not reuse default-database password auth for an arbitrary target alias."""

    from apps.data_center.management.commands import manage_financial_numeric_catalog

    def forbidden_authentication(_prompt: str) -> str:
        """Fail if the command prompts for a password before alias validation."""

        pytest.fail("non-default database was rejected only after starting authentication")

    def forbidden_document_fetch(*_args: object, **_kwargs: object) -> object:
        """Fail if a non-default alias reaches the controlled-egress request."""

        pytest.fail("non-default database reached provider HTTP")

    monkeypatch.setattr(manage_financial_numeric_catalog, "getpass", forbidden_authentication)
    monkeypatch.setattr(
        manage_financial_numeric_catalog,
        "execute_provider_document_request",
        forbidden_document_fetch,
    )
    before_providers = ProviderConfigModel.objects.count()
    before_audits = EgressRequestAuditModel.objects.count()
    before_captures = FinancialNumericSourceDocumentCaptureModel.objects.count()

    with pytest.raises(CommandError, match="default database"):
        manage_financial_numeric_catalog.Command().handle(
            action="capture",
            owner="synthetic-owner",
            database="numeric-catalog-other",
        )

    assert ProviderConfigModel.objects.count() == before_providers
    assert EgressRequestAuditModel.objects.count() == before_audits
    assert FinancialNumericSourceDocumentCaptureModel.objects.count() == before_captures
