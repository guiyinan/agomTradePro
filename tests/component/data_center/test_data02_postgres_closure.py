"""Opt-in PostgreSQL evidence for DATA-02 identity and attempt gates."""

from __future__ import annotations

import dataclasses
import importlib
import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from typing import cast
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.models import Model
from django.db.utils import load_backend

from apps.data_center.application.batch_identity import ProviderAssetIdentityError
from apps.data_center.application.current_valuation_sync import (
    SyncCurrentValuationBatchUseCase,
)
from apps.data_center.application.dtos import SyncQuoteRequest, SyncValuationRequest
from apps.data_center.application.sync_identity import build_sync_execution_identity
from apps.data_center.application.sync_use_cases import SyncQuoteUseCase, SyncValuationUseCase
from apps.data_center.domain.control_plane import (
    SyncBatch,
    SyncItemAttempt,
    SyncItemAttemptPhase,
    SyncItemAttemptState,
    SyncItemState,
)
from apps.data_center.domain.entities import ProviderConfig, QuoteSnapshot, RawAudit, ValuationFact
from apps.data_center.infrastructure.control_plane_repositories import (
    SyncBatchRepository,
    SyncItemAttemptRepository,
)
from apps.data_center.infrastructure.models import (
    QuoteSnapshotModel,
    SyncBatchModel,
    SyncItemAttemptModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository

_POSTGRES_FLAG = "AGOM_DATA02_POSTGRES_TEST"
_POSTGRES_URL = "AGOM_DATA02_POSTGRES_TEST_DATABASE_URL"
_DATABASE_NAME = "data02_closure_test"
_NOW = datetime(2026, 9, 21, 11, 30, tzinfo=UTC)
_UNIVERSE_HASH = "b" * 64
_AUTHORITY_HASH = "a" * 64
_VAL_DATE = date(2026, 9, 19)


@dataclass(frozen=True)
class _WorkerResult:
    """Sanitized outcome from one independent PostgreSQL connection."""

    backend_pid: int
    outcome: str
    detail: str


def _credentials() -> dict[str, object]:
    """Read an explicitly enabled disposable loopback PostgreSQL target."""

    if os.environ.get(_POSTGRES_FLAG, "").strip() != "1":
        pytest.skip(f"{_POSTGRES_FLAG}=1 is required for the private PostgreSQL fixture")
    raw_url = os.environ.get(_POSTGRES_URL, "").strip()
    if not raw_url:
        pytest.fail(f"{_POSTGRES_URL} is required")
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        pytest.fail("private PostgreSQL URL must use a PostgreSQL scheme")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("private PostgreSQL URL must target loopback")
    if unquote(parsed.path.removeprefix("/")) != _DATABASE_NAME:
        pytest.fail("private PostgreSQL URL database identity mismatch")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": _DATABASE_NAME,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
    }


def _database_observation(wrapper: object) -> tuple[str, int, int]:
    """Return database identity, public-table count and other client count."""

    with wrapper.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT current_database(), "
            "(SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'), "
            "(SELECT COUNT(*) FROM pg_stat_activity "
            "WHERE datname = current_database() "
            "AND backend_type = 'client backend' AND pid <> pg_backend_pid())"
        )
        row = cursor.fetchone()
    if row is None:
        raise AssertionError("private PostgreSQL observation returned no row")
    return str(row[0]), int(row[1]), int(row[2])


@pytest.fixture(scope="module")
def _data02_postgres_schema(django_db_blocker: object) -> Iterator[None]:
    """Own only DATA-02 evidence tables in an empty private database."""

    credentials = _credentials()
    original = connections["default"]
    original_database_settings = deepcopy(connections.databases["default"])
    database_settings = deepcopy(original.settings_dict)
    database_settings.update(
        ENGINE="django.db.backends.postgresql",
        NAME=_DATABASE_NAME,
        USER=credentials["user"],
        PASSWORD=credentials["password"],
        HOST=credentials["host"],
        PORT=str(credentials["port"]),
        CONN_MAX_AGE=0,
        OPTIONS={"connect_timeout": 10, "sslmode": "disable", "gssencmode": "disable"},
    )
    wrapper = load_backend(database_settings["ENGINE"]).DatabaseWrapper(
        database_settings,
        alias="default",
    )
    created: list[type[Model]] = []
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        connections.databases["default"] = database_settings
        connections["default"] = wrapper
        try:
            if wrapper.vendor != "postgresql":
                pytest.fail("item-attempt fixture resolved a non-PostgreSQL backend")
            database_name, table_count, other_clients = _database_observation(wrapper)
            assert database_name == _DATABASE_NAME
            assert table_count == 0
            assert other_clients == 0
            with wrapper.schema_editor() as editor:
                for model in (
                    QuoteSnapshotModel,
                    ValuationFactModel,
                    SyncBatchModel,
                    SyncItemAttemptModel,
                ):
                    editor.create_model(model)
                    created.append(model)
            yield
        finally:
            close_old_connections()
            if created:
                with wrapper.schema_editor() as editor:
                    for model in reversed(created):
                        editor.delete_model(model)
                database_name, table_count, other_clients = _database_observation(wrapper)
                assert database_name == _DATABASE_NAME
                assert table_count == 0
                assert other_clients == 0
            wrapper.close()
            connections["default"] = original
            connections.databases["default"] = original_database_settings


@pytest.fixture(autouse=True)
def _use_private_postgres(_data02_postgres_schema: None) -> None:
    """Keep the module bound to its private PostgreSQL schema."""

    del _data02_postgres_schema


@pytest.fixture(autouse=True)
def _clear_data02_tables() -> Iterator[None]:
    """Isolate mutable fact proofs while retaining append-only attempt evidence."""

    for model in (ValuationFactModel, QuoteSnapshotModel):
        model._default_manager.all().delete()
    yield
    for model in (ValuationFactModel, QuoteSnapshotModel):
        model._default_manager.all().delete()


def _saved_batch() -> SyncBatch:
    batch = SyncBatch(
        batch_id=str(uuid4()),
        run_id=str(uuid4()),
        dataset_key="equity.core.backfill",
        provider_name="tushare",
        idempotency_key=f"equity.core.backfill:tushare:{uuid4()}",
        state=SyncItemState.RUNNING,
        requested=1,
        started_at=_NOW,
    )
    return SyncBatchRepository().save(batch)


def _running_attempt(
    batch: SyncBatch,
    *,
    execution_token: str,
    universe_hash: str = _UNIVERSE_HASH,
    asset_code: str = "000001.SZ",
    attempt_number: int = 1,
    started_at: datetime = _NOW,
) -> SyncItemAttempt:
    return SyncItemAttempt(
        attempt_id=str(uuid4()),
        run_id=batch.run_id,
        batch_id=batch.batch_id,
        dataset_key=batch.dataset_key,
        asset_code=asset_code,
        phase=SyncItemAttemptPhase.QUOTE,
        attempt_number=attempt_number,
        state=SyncItemAttemptState.RUNNING,
        execution_token=execution_token,
        started_at=started_at,
        universe_hash=universe_hash,
        authority_content_hash=_AUTHORITY_HASH,
    )


def _backend_pid() -> int:
    with connection.cursor() as cursor:
        cursor.execute("SET lock_timeout = '5s'")
        cursor.execute("SELECT pg_backend_pid()")
        row = cursor.fetchone()
    if row is None:
        raise AssertionError("PostgreSQL backend pid query returned no row")
    return int(row[0])


def _run_worker(barrier: Barrier, operation: Callable[[], str]) -> _WorkerResult:
    close_old_connections()
    try:
        backend_pid = _backend_pid()
        barrier.wait(timeout=8)
        try:
            return _WorkerResult(backend_pid, "succeeded", operation())
        except (ValueError, DatabaseError) as exc:
            return _WorkerResult(backend_pid, "rejected", str(exc))
    finally:
        connection.close()


def _run_concurrently(*operations: Callable[[], str]) -> list[_WorkerResult]:
    barrier = Barrier(len(operations))
    with ThreadPoolExecutor(
        max_workers=len(operations), thread_name_prefix="data02-item-pg"
    ) as pool:
        futures = [pool.submit(_run_worker, barrier, operation) for operation in operations]
        try:
            return [future.result(timeout=25) for future in futures]
        except FutureTimeoutError:
            pytest.fail("item-attempt PostgreSQL concurrency exceeded 25 seconds")


def _publish_main_connection_setup() -> None:
    """Commit setup rows and release the main backend before worker races."""

    if connection.in_atomic_block:
        raise AssertionError("concurrency setup must not run inside an atomic block")
    connection.commit()
    connection.close()


class _Provider:
    """Return a fixed provider payload for all guarded valuation/quote paths."""

    def __init__(
        self,
        *,
        quotes: list[QuoteSnapshot] | None = None,
        valuations: list[ValuationFact] | None = None,
    ) -> None:
        self._quotes = list(quotes or [])
        self._valuations = list(valuations or [])

    def provider_name(self) -> str:
        return "provider-main"

    def fetch_quote_snapshots(self, _asset_codes: list[str]) -> list[QuoteSnapshot]:
        return list(self._quotes)

    def fetch_current_valuations(
        self, _asset_codes: list[str], _as_of_date: date
    ) -> list[ValuationFact]:
        return list(self._valuations)

    def fetch_valuations(
        self, _asset_code: str, _start_date: date, _end_date: date
    ) -> list[ValuationFact]:
        return list(self._valuations)


class _ProviderRepository:
    def __init__(self) -> None:
        self.config = ProviderConfig(
            id=1,
            name="provider-main",
            source_type="tushare",
            is_active=True,
            priority=1,
            api_key="",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={},
            description="",
        )

    def get_by_id(self, _provider_id: int) -> ProviderConfig:
        return self.config

    def save(self, config: ProviderConfig) -> ProviderConfig:
        self.config = config
        return config


class _Registry:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider

    def get_by_id(self, _provider_id: int) -> _Provider:
        return self.provider

    def record_success(self, *_args: object) -> None:
        return None

    def record_failure(self, *_args: object) -> None:
        return None

    def get_all_statuses(self) -> list[object]:
        return []


class _RawAuditRepository:
    def log(self, audit: RawAudit) -> RawAudit:
        return dataclasses.replace(
            audit,
            raw_audit_id=str(uuid4()),
            content_hash="d" * 64,
        )


class _TransactionUnitOfWork:
    @property
    def unit_of_work_key(self) -> str:
        return "django:default"

    def atomic(self) -> AbstractContextManager[None]:
        return cast(AbstractContextManager[None], transaction.atomic())


class _IdentityIssuer:
    def issue(self, *, dataset_key: str, provider_name: str):
        return build_sync_execution_identity(
            run_id="11111111-1111-4111-8111-111111111111",
            ingested_run_id="22222222-2222-4222-8222-222222222222",
            batch_id="33333333-3333-4333-8333-333333333333",
            dataset_key=dataset_key,
            provider_name=provider_name,
        )


class _AuditWriter:
    @property
    def database_alias(self) -> str:
        return "default"

    def write(self, _observation: object) -> object:
        return SimpleNamespace()


class _Clock:
    def now(self) -> datetime:
        return _NOW


class _Publisher:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def execute(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        return SimpleNamespace()


class _QualityRecorder:
    def execute(self, **_kwargs: object) -> object:
        raise AssertionError("identity rejection must not record publication quality")


def _quote(asset_code: str) -> QuoteSnapshot:
    return QuoteSnapshot(
        asset_code=asset_code,
        snapshot_at=_NOW,
        fetched_at=_NOW,
        current_price=10.5,
        source="provider-main",
        extra={"proof": "provider-payload"},
    )


def _valuation(asset_code: str) -> ValuationFact:
    return ValuationFact(
        asset_code=asset_code,
        val_date=_VAL_DATE,
        pe_ttm=12.3,
        pb=1.7,
        source="provider-main",
        observed_at=_NOW,
        available_at=_NOW,
        fetched_at=_NOW,
        extra={"proof": "provider-payload"},
    )


def _seed_quote() -> None:
    QuoteSnapshotRepository().bulk_upsert(
        [dataclasses.replace(_quote("000001.SZ"), current_price=9.75, source="tushare")]
    )


def _seed_valuation() -> None:
    ValuationFactRepository().bulk_upsert(
        [dataclasses.replace(_valuation("000001.SZ"), pe_ttm=9.1, source="tushare")]
    )


def _quote_rows() -> list[dict[str, object]]:
    return list(QuoteSnapshotModel._default_manager.order_by("id").values())


def _valuation_rows() -> list[dict[str, object]]:
    return list(ValuationFactModel._default_manager.order_by("id").values())


@pytest.mark.parametrize(
    ("requested", "returned"),
    [
        (["000001.SZ"], ["600000.SH"]),
        (["000001.SZ", "600000.SH"], ["000001.SZ"]),
        (["000001.SZ"], ["000001.SZ", "000001.SZ"]),
    ],
    ids=("substituted", "missing", "duplicate"),
)
def test_postgresql_quote_identity_rejection_leaves_fact_rows_unchanged(
    requested: list[str], returned: list[str]
) -> None:
    """Strict quote identity failure leaves no PostgreSQL fact residue."""

    _seed_quote()
    before = _quote_rows()
    publisher = _Publisher()
    provider = _Provider(quotes=[_quote(asset_code) for asset_code in returned])
    use_case = SyncQuoteUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_Registry(provider),
        fact_repo=QuoteSnapshotRepository(),
        raw_audit_repo=_RawAuditRepository(),
        publication_publisher=publisher,  # type: ignore[arg-type]
        sync_identity_issuer=_IdentityIssuer(),
        sync_unit_of_work=_TransactionUnitOfWork(),
        data_fetch_audit_writer=_AuditWriter(),
        data_publication_audit_writer=_AuditWriter(),
        publication_quality_recorder=_QualityRecorder(),
        clock=_Clock(),
    )

    with pytest.raises(ProviderAssetIdentityError) as caught:
        use_case.execute(
            SyncQuoteRequest(
                provider_id=1,
                asset_codes=requested,
                require_exact_asset_codes=True,
            )
        )

    assert caught.value.code == "PROVIDER_ASSET_IDENTITY_MISMATCH"
    assert _quote_rows() == before
    assert publisher.calls == []


@pytest.mark.parametrize(
    ("requested", "returned"),
    [
        (["000001.SZ"], ["600000.SH"]),
        (["000001.SZ", "600000.SH"], ["000001.SZ"]),
        (["000001.SZ"], ["000001.SZ", "000001.SZ"]),
    ],
    ids=("substituted", "missing", "duplicate"),
)
def test_postgresql_current_valuation_identity_rejection_leaves_rows_unchanged(
    requested: list[str], returned: list[str]
) -> None:
    """Strict current valuation failure leaves no PostgreSQL fact residue."""

    _seed_valuation()
    before = _valuation_rows()
    publisher = _Publisher()
    provider = _Provider(valuations=[_valuation(asset_code) for asset_code in returned])
    use_case = SyncCurrentValuationBatchUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_Registry(provider),
        fact_repo=ValuationFactRepository(),
        raw_audit_repo=_RawAuditRepository(),
        publication_publisher=publisher,  # type: ignore[arg-type]
    )

    with pytest.raises(ProviderAssetIdentityError) as caught:
        use_case.execute(
            provider_id=1,
            asset_codes=requested,
            as_of_date=_VAL_DATE,
            require_exact_asset_codes=True,
        )

    assert caught.value.code == "PROVIDER_ASSET_IDENTITY_MISMATCH"
    assert _valuation_rows() == before
    assert publisher.calls == []


def test_postgresql_single_valuation_substitution_leaves_rows_unchanged() -> None:
    """Single-asset valuation rejects substitution before a real repository write."""

    _seed_valuation()
    before = _valuation_rows()
    publisher = _Publisher()
    provider = _Provider(valuations=[_valuation("600000.SH")])
    use_case = SyncValuationUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_Registry(provider),
        fact_repo=ValuationFactRepository(),
        raw_audit_repo=_RawAuditRepository(),
        publication_publisher=publisher,  # type: ignore[arg-type]
    )

    with pytest.raises(ProviderAssetIdentityError) as caught:
        use_case.execute(
            SyncValuationRequest(
                provider_id=1,
                asset_code="000001.SZ",
                start=_VAL_DATE,
                end=_VAL_DATE,
            )
        )

    assert caught.value.code == "PROVIDER_ASSET_IDENTITY_MISMATCH"
    assert _valuation_rows() == before
    assert publisher.calls == []


def test_postgresql_running_attempt_constraint_and_migration_preflight_are_active() -> None:
    """The private PostgreSQL schema exposes the conditional unique gate."""

    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(
            cursor, SyncItemAttemptModel._meta.db_table
        )
    constraint = constraints["dc_item_one_running"]
    assert constraint["unique"] is True
    assert constraint["columns"] == ["batch_id", "asset_code", "phase"]

    migration = importlib.import_module(
        "apps.data_center.migrations.0081_sync_item_attempt_running_unique"
    )
    migration.assert_no_duplicate_running_attempts(
        django_apps,
        cast(BaseDatabaseSchemaEditor, object()),
    )


def _insert_running_attempt_directly(attempt: SyncItemAttempt) -> str:
    """Bypass repository checks so PostgreSQL alone must enforce the gate."""

    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO data_center_sync_item_attempt "
            "(attempt_id, run_id, batch_id, dataset_key, asset_code, phase, "
            "attempt_number, state, execution_token, started_at, finished_at, "
            "stored_count, error_code, error_message, universe_hash, "
            "authority_content_hash, evidence_hash, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, "
            "0, '', '', %s, %s, '', %s, %s)",
            [
                attempt.attempt_id,
                attempt.run_id,
                attempt.batch_id,
                attempt.dataset_key,
                attempt.asset_code,
                attempt.phase.value,
                attempt.attempt_number,
                attempt.state.value,
                attempt.execution_token,
                attempt.started_at,
                attempt.universe_hash,
                attempt.authority_content_hash,
                _NOW,
                _NOW,
            ],
        )
    return attempt.execution_token


def test_postgresql_partial_unique_constraint_rejects_concurrent_running_rows() -> None:
    """Direct concurrent inserts cannot create two active leases for one item."""

    batch = _saved_batch()
    first = _running_attempt(batch, execution_token="constraint-a")
    second = _running_attempt(
        batch,
        execution_token="constraint-b",
        attempt_number=2,
    )
    _publish_main_connection_setup()

    results = _run_concurrently(
        lambda: _insert_running_attempt_directly(first),
        lambda: _insert_running_attempt_directly(second),
    )

    assert len({result.backend_pid for result in results}) == 2
    assert sorted(result.outcome for result in results) == ["rejected", "succeeded"]
    loser = next(result for result in results if result.outcome == "rejected")
    assert "dc_item_one_running" in loser.detail
    assert (
        SyncItemAttemptModel._default_manager.filter(
            batch_id=batch.batch_id,
            asset_code="000001.SZ",
            phase=SyncItemAttemptPhase.QUOTE.value,
            state=SyncItemAttemptState.RUNNING.value,
        ).count()
        == 1
    )


def test_postgresql_concurrent_begin_has_one_winner_for_same_item_binding() -> None:
    """The batch lock serializes two attempts with the same frozen binding."""

    batch = _saved_batch()
    first = _running_attempt(batch, execution_token="worker-a")
    second = _running_attempt(
        batch,
        execution_token="worker-b",
        attempt_number=2,
    )
    _publish_main_connection_setup()

    results = _run_concurrently(
        lambda: SyncItemAttemptRepository().begin(first).state.value,
        lambda: SyncItemAttemptRepository().begin(second).state.value,
    )

    assert len({result.backend_pid for result in results}) == 2
    assert sorted(result.outcome for result in results) == ["rejected", "succeeded"]
    loser = next(result for result in results if result.outcome == "rejected")
    assert loser.detail in {
        "active attempt already exists for this item phase",
        "attempt_number must be the next monotonic value 1",
    }
    rows = list(SyncItemAttemptModel._default_manager.filter(batch_id=batch.batch_id))
    assert len(rows) == 1
    assert rows[0].attempt_number == 1
    assert rows[0].universe_hash == _UNIVERSE_HASH


def test_postgresql_concurrent_finish_applies_one_terminal_transition() -> None:
    """Two finishers cannot overwrite one another's terminal evidence."""

    batch = _saved_batch()
    running = _running_attempt(batch, execution_token="finish-race")
    SyncItemAttemptRepository().begin(running)
    succeeded = running.finish(
        state=SyncItemAttemptState.SUCCEEDED,
        finished_at=_NOW + timedelta(seconds=1),
        stored_count=1,
    )
    failed = running.finish(
        state=SyncItemAttemptState.FAILED,
        finished_at=_NOW + timedelta(seconds=1),
        error_code="provider_failed",
    )
    _publish_main_connection_setup()

    results = _run_concurrently(
        lambda: SyncItemAttemptRepository().finish(succeeded).state.value,
        lambda: SyncItemAttemptRepository().finish(failed).state.value,
    )

    assert len({result.backend_pid for result in results}) == 2
    assert sorted(result.outcome for result in results) == ["rejected", "succeeded"]
    loser = next(result for result in results if result.outcome == "rejected")
    assert "already terminal" in loser.detail
    row = SyncItemAttemptModel._default_manager.get(attempt_id=running.attempt_id)
    assert row.state in {SyncItemAttemptState.SUCCEEDED.value, SyncItemAttemptState.FAILED.value}
    assert row.finished_at == _NOW + timedelta(seconds=1)
    if row.state == SyncItemAttemptState.SUCCEEDED.value:
        assert row.stored_count == 1
        assert row.error_code == ""
    else:
        assert row.stored_count == 0
        assert row.error_code == "provider_failed"


def test_postgresql_recovery_and_finish_converge_on_one_terminal_state() -> None:
    """Stale recovery and normal finish serialize without rewriting terminal history."""

    batch = _saved_batch()
    running = _running_attempt(batch, execution_token="recover-race")
    SyncItemAttemptRepository().begin(running)
    succeeded = running.finish(
        state=SyncItemAttemptState.SUCCEEDED,
        finished_at=_NOW + timedelta(seconds=2),
        stored_count=1,
    )
    _publish_main_connection_setup()

    def recover() -> str:
        recovered = SyncItemAttemptRepository().recover_interrupted(
            batch_id=batch.batch_id,
            phase=SyncItemAttemptPhase.QUOTE,
            before=_NOW + timedelta(seconds=1),
            finished_at=_NOW + timedelta(seconds=2),
        )
        return recovered[0].state.value if recovered else "noop"

    results = _run_concurrently(
        recover,
        lambda: SyncItemAttemptRepository().finish(succeeded).state.value,
    )

    assert len({result.backend_pid for result in results}) == 2
    assert sum(result.outcome == "succeeded" for result in results) >= 1
    row = SyncItemAttemptModel._default_manager.get(attempt_id=running.attempt_id)
    assert row.state in {
        SyncItemAttemptState.SUCCEEDED.value,
        SyncItemAttemptState.INTERRUPTED.value,
    }
    assert row.finished_at == _NOW + timedelta(seconds=2)


def test_postgresql_concurrent_recovery_transitions_stale_row_once() -> None:
    """Two recoverers converge and preserve a fresh RUNNING attempt."""

    batch = _saved_batch()
    stale = _running_attempt(batch, execution_token="stale")
    fresh = _running_attempt(
        batch,
        execution_token="fresh",
        asset_code="000002.SZ",
        started_at=_NOW + timedelta(seconds=2),
    )
    repository = SyncItemAttemptRepository()
    repository.begin(stale)
    repository.begin(fresh)
    _publish_main_connection_setup()

    def recover() -> str:
        recovered = SyncItemAttemptRepository().recover_interrupted(
            batch_id=batch.batch_id,
            phase=SyncItemAttemptPhase.QUOTE,
            before=_NOW + timedelta(seconds=1),
            finished_at=_NOW + timedelta(seconds=3),
        )
        return ",".join(item.state.value for item in recovered) or "noop"

    results = _run_concurrently(recover, recover)

    assert len({result.backend_pid for result in results}) == 2
    assert all(result.outcome == "succeeded" for result in results)
    assert sorted(result.detail for result in results) == ["interrupted", "noop"]
    stale_row = SyncItemAttemptModel._default_manager.get(attempt_id=stale.attempt_id)
    fresh_row = SyncItemAttemptModel._default_manager.get(attempt_id=fresh.attempt_id)
    assert stale_row.state == SyncItemAttemptState.INTERRUPTED.value
    assert fresh_row.state == SyncItemAttemptState.RUNNING.value
