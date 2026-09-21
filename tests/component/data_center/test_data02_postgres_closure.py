"""Opt-in PostgreSQL evidence for DATA-02 identity and attempt gates."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from typing import Any, cast
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

from apps.data_center.application.backfill_control_plane import backfill_execution_token
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
from apps.data_center.infrastructure.backfill_item_attempt_store import (
    DjangoBackfillItemAttemptStore,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    SyncBatchRepository,
    SyncItemAttemptRepository,
    SyncRunRepository,
)
from apps.data_center.infrastructure.models import (
    QuoteSnapshotModel,
    SyncBatchModel,
    SyncItemAttemptModel,
    SyncRunModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository

_POSTGRES_FLAG = "AGOM_DATA02_POSTGRES_TEST"
_SCALE_FLAG = "AGOM_DATA02_SCALE_TEST"
_POSTGRES_URL = "AGOM_DATA02_POSTGRES_TEST_DATABASE_URL"
_DATABASE_NAME = "data02_closure_test"
_NOW = datetime(2026, 9, 21, 11, 30, tzinfo=UTC)
_UNIVERSE_HASH = "b" * 64
_AUTHORITY_HASH = "a" * 64
_VAL_DATE = date(2026, 9, 19)
_CURRENT_DENOMINATOR = 5_565
_BACKFILL_BATCH_SIZE = 200
_CONCURRENCY_LOCK_TIMEOUT_SECONDS = 20
_CONCURRENCY_RESULT_TIMEOUT_SECONDS = 60


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
                    SyncRunModel,
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
        cursor.execute(
            "SELECT set_config('lock_timeout', %s, false)",
            [f"{_CONCURRENCY_LOCK_TIMEOUT_SECONDS}s"],
        )
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
            return [
                future.result(timeout=_CONCURRENCY_RESULT_TIMEOUT_SECONDS) for future in futures
            ]
        except FutureTimeoutError:
            pytest.fail(
                "item-attempt PostgreSQL concurrency exceeded "
                f"{_CONCURRENCY_RESULT_TIMEOUT_SECONDS} seconds"
            )


def _publish_main_connection_setup() -> None:
    """Commit setup rows and release the main backend before worker races."""

    if connection.in_atomic_block:
        raise AssertionError("concurrency setup must not run inside an atomic block")
    connection.commit()
    connection.close()


class _QueryCounter:
    """Count database execute calls without retaining large SQL payloads."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(
        self,
        execute: Callable[..., Any],
        sql: str,
        params: object,
        many: bool,
        context: dict[str, object],
    ) -> Any:
        self.count += 1
        return execute(sql, params, many, context)


def _scale_asset_codes() -> list[str]:
    """Return a deterministic cardinality-equivalent current-universe workload."""

    return [f"{number:06d}.SZ" for number in range(1, _CURRENT_DENOMINATOR + 1)]


def _scale_universe_hash(asset_codes: list[str]) -> str:
    """Use the production backfill canonical universe encoding."""

    payload = json.dumps(
        {
            "schema": "active-a-share-universe.v1",
            "asset_codes": sorted(asset_codes),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _attempt_relation_size() -> tuple[int, int, int]:
    """Return total, table and index bytes for the item-attempt relation."""

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_total_relation_size(%s), pg_relation_size(%s), " "pg_indexes_size(%s)",
            [
                SyncItemAttemptModel._meta.db_table,
                SyncItemAttemptModel._meta.db_table,
                SyncItemAttemptModel._meta.db_table,
            ],
        )
        row = cursor.fetchone()
    if row is None:
        raise AssertionError("item-attempt relation size query returned no row")
    return int(row[0]), int(row[1]), int(row[2])


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


def test_postgresql_mixed_terminal_values_update_atomically() -> None:
    """PostgreSQL VALUES updates preserve heterogeneous terminal evidence."""

    batch = _saved_batch()
    repository = SyncItemAttemptRepository()
    running = repository.begin_many(
        (
            _running_attempt(
                batch,
                execution_token="mixed-terminal-a",
                asset_code="000001.SZ",
            ),
            _running_attempt(
                batch,
                execution_token="mixed-terminal-b",
                asset_code="000002.SZ",
            ),
        )
    )
    terminal = (
        running[0].finish(
            state=SyncItemAttemptState.SUCCEEDED,
            finished_at=_NOW + timedelta(seconds=1),
            stored_count=17,
        ),
        running[1].finish(
            state=SyncItemAttemptState.FAILED,
            finished_at=_NOW + timedelta(seconds=1),
            error_code="zero_output",
        ),
    )

    assert repository.finish_many(terminal) == list(terminal)
    rows = repository.list_for_batch(batch.batch_id)
    assert [(item.state, item.stored_count, item.error_code) for item in rows] == [
        (SyncItemAttemptState.SUCCEEDED, 17, ""),
        (SyncItemAttemptState.FAILED, 0, "zero_output"),
    ]


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


def test_postgresql_current_denominator_item_attempt_scale() -> None:
    """Measure the exact 5N attempt shape at the current 5,565 denominator."""

    if os.environ.get(_SCALE_FLAG, "").strip() != "1":
        pytest.skip(f"{_SCALE_FLAG}=1 is required for the 5,565-item scale measurement")
    asset_codes = _scale_asset_codes()
    universe_hash = _scale_universe_hash(asset_codes)
    authority_hash = "c" * 64
    phases = (
        SyncItemAttemptPhase.QUOTE,
        SyncItemAttemptPhase.VALUATION,
        SyncItemAttemptPhase.PRICE,
        SyncItemAttemptPhase.FINANCIAL,
    )
    store = DjangoBackfillItemAttemptStore(
        run_repository=SyncRunRepository(),
        batch_repository=SyncBatchRepository(),
        attempt_repository=SyncItemAttemptRepository(),
    )
    relation_before = _attempt_relation_size()
    query_counter = _QueryCounter()
    begin_seconds = 0.0
    finish_seconds = 0.0
    batch_ids: set[str] = set()
    batch_keys: list[str] = []

    with connection.execute_wrapper(query_counter):
        for offset in range(0, len(asset_codes), _BACKFILL_BATCH_SIZE):
            batch_codes = asset_codes[offset : offset + _BACKFILL_BATCH_SIZE]
            idempotency_key = f"data02-scale:{universe_hash}:{offset}"
            batch_keys.append(idempotency_key)
            execution_token = backfill_execution_token(idempotency_key)
            for phase in phases:
                phase_started = time.perf_counter()
                attempts = store.begin_many(
                    idempotency_key=idempotency_key,
                    provider_name="scale-fixture",
                    asset_codes=batch_codes,
                    phase=phase,
                    execution_token=execution_token,
                    started_at=_NOW,
                    universe_hash=universe_hash,
                    authority_content_hash=authority_hash,
                    requested=len(batch_codes),
                )
                begin_seconds += time.perf_counter() - phase_started
                batch_ids.add(attempts[0].batch_id)
                phase_finished = time.perf_counter()
                store.finish_many(
                    [
                        attempt.finish(
                            state=SyncItemAttemptState.SUCCEEDED,
                            finished_at=_NOW + timedelta(seconds=1),
                            stored_count=(index % 17) + 1,
                        )
                        for index, attempt in enumerate(attempts)
                    ]
                )
                finish_seconds += time.perf_counter() - phase_finished

        publication_key = batch_keys[-1]
        publication_token = backfill_execution_token(publication_key)
        publication_started = time.perf_counter()
        publication_attempts = store.begin_many(
            idempotency_key=publication_key,
            provider_name="scale-fixture",
            asset_codes=asset_codes,
            phase=SyncItemAttemptPhase.PUBLICATION,
            execution_token=publication_token,
            started_at=_NOW,
            universe_hash=universe_hash,
            authority_content_hash=authority_hash,
            requested=len(asset_codes[-_BACKFILL_BATCH_SIZE:]),
        )
        begin_seconds += time.perf_counter() - publication_started
        publication_finished = time.perf_counter()
        store.finish_many(
            [
                attempt.finish(
                    state=SyncItemAttemptState.SUCCEEDED,
                    finished_at=_NOW + timedelta(seconds=1),
                    stored_count=1,
                    evidence_hash="d" * 64,
                )
                for attempt in publication_attempts
            ]
        )
        finish_seconds += time.perf_counter() - publication_finished

    expected_success_rows = len(asset_codes) * 5
    scale_rows = SyncItemAttemptModel._default_manager.filter(batch_id__in=batch_ids)
    assert scale_rows.count() == expected_success_rows
    assert scale_rows.filter(state=SyncItemAttemptState.RUNNING.value).count() == 0
    assert scale_rows.filter(state=SyncItemAttemptState.SUCCEEDED.value).count() == (
        expected_success_rows
    )
    assert scale_rows.exclude(attempt_number=1).count() == 0
    phase_counts = {
        phase.value: scale_rows.filter(phase=phase.value).count()
        for phase in (*phases, SyncItemAttemptPhase.PUBLICATION)
    }
    assert set(phase_counts.values()) == {len(asset_codes)}

    final_batch_id = publication_attempts[0].batch_id
    list_counter = _QueryCounter()
    list_started = time.perf_counter()
    with connection.execute_wrapper(list_counter):
        final_batch_attempts = SyncItemAttemptRepository().list_for_batch(final_batch_id)
    list_seconds = time.perf_counter() - list_started
    expected_final_batch_rows = len(asset_codes) + (len(asset_codes) % _BACKFILL_BATCH_SIZE) * len(
        phases
    )
    assert len(final_batch_attempts) == expected_final_batch_rows

    recovery_store = DjangoBackfillItemAttemptStore(
        run_repository=SyncRunRepository(),
        batch_repository=SyncBatchRepository(),
        attempt_repository=SyncItemAttemptRepository(),
    )
    recovery_key = f"data02-scale-recovery:{universe_hash}"
    recovery_token = backfill_execution_token(recovery_key)
    recovery_seed_counter = _QueryCounter()
    recovery_seed_started = time.perf_counter()
    with connection.execute_wrapper(recovery_seed_counter):
        stale_attempts = recovery_store.begin_many(
            idempotency_key=recovery_key,
            provider_name="scale-fixture",
            asset_codes=asset_codes,
            phase=SyncItemAttemptPhase.PUBLICATION,
            execution_token=recovery_token,
            started_at=_NOW,
            universe_hash=universe_hash,
            authority_content_hash=authority_hash,
            requested=len(asset_codes),
        )
        fresh_attempt = recovery_store.begin(
            idempotency_key=recovery_key,
            provider_name="scale-fixture",
            asset_code="999999.SZ",
            phase=SyncItemAttemptPhase.PUBLICATION,
            execution_token=recovery_token,
            started_at=_NOW + timedelta(hours=2),
            universe_hash=universe_hash,
            authority_content_hash=authority_hash,
            requested=len(asset_codes),
        )
    recovery_seed_seconds = time.perf_counter() - recovery_seed_started
    assert len(stale_attempts) == len(asset_codes)
    recovery_batch_id = stale_attempts[0].batch_id

    recovery_counter = _QueryCounter()
    recovery_started = time.perf_counter()
    with connection.execute_wrapper(recovery_counter):
        recovered = SyncItemAttemptRepository().recover_interrupted(
            batch_id=recovery_batch_id,
            phase=SyncItemAttemptPhase.PUBLICATION,
            before=_NOW + timedelta(hours=1),
            finished_at=_NOW + timedelta(hours=1),
        )
    recovery_seconds = time.perf_counter() - recovery_started
    assert len(recovered) == len(asset_codes)
    assert all(item.state is SyncItemAttemptState.INTERRUPTED for item in recovered)
    fresh_row = SyncItemAttemptModel._default_manager.get(attempt_id=fresh_attempt.attempt_id)
    assert fresh_row.state == SyncItemAttemptState.RUNNING.value
    assert fresh_row.finished_at is None

    aggregate_counter = _QueryCounter()
    aggregate_started = time.perf_counter()
    measured_batch_ids = {*batch_ids, recovery_batch_id}
    with connection.execute_wrapper(aggregate_counter):
        terminal_counts = {
            state: SyncItemAttemptModel._default_manager.filter(
                batch_id__in=measured_batch_ids,
                state=state,
            ).count()
            for state in (
                SyncItemAttemptState.SUCCEEDED.value,
                SyncItemAttemptState.INTERRUPTED.value,
                SyncItemAttemptState.RUNNING.value,
            )
        }
    aggregate_seconds = time.perf_counter() - aggregate_started
    assert terminal_counts == {
        SyncItemAttemptState.SUCCEEDED.value: expected_success_rows,
        SyncItemAttemptState.INTERRUPTED.value: len(asset_codes),
        SyncItemAttemptState.RUNNING.value: 1,
    }

    with connection.cursor() as cursor:
        cursor.execute(
            "EXPLAIN (FORMAT JSON) SELECT attempt_id FROM "
            "data_center_sync_item_attempt WHERE batch_id = %s AND state = %s",
            [final_batch_id, SyncItemAttemptState.SUCCEEDED.value],
        )
        explain_row = cursor.fetchone()
    if explain_row is None:
        raise AssertionError("item-attempt EXPLAIN returned no row")
    relation_after = _attempt_relation_size()
    metrics = {
        "schema": "data02-item-attempt-scale.v1",
        "classification": "cardinality-equivalent synthetic PostgreSQL measurement",
        "measurement_only": True,
        "production_acceptance": False,
        "denominator": len(asset_codes),
        "legacy_denominator_superseded": 5_533,
        "batch_size": _BACKFILL_BATCH_SIZE,
        "batch_count": len(batch_keys),
        "universe_hash": universe_hash,
        "success_rows": expected_success_rows,
        "phase_counts": phase_counts,
        "final_batch_rows": len(final_batch_attempts),
        "begin_seconds": round(begin_seconds, 6),
        "finish_seconds": round(finish_seconds, 6),
        "success_execute_calls": query_counter.count,
        "list_seconds": round(list_seconds, 6),
        "list_execute_calls": list_counter.count,
        "recovery_seed_rows": len(stale_attempts) + 1,
        "recovery_seed_seconds": round(recovery_seed_seconds, 6),
        "recovery_seed_execute_calls": recovery_seed_counter.count,
        "recovered_rows": len(recovered),
        "recovery_seconds": round(recovery_seconds, 6),
        "recovery_execute_calls": recovery_counter.count,
        "aggregate_seconds": round(aggregate_seconds, 6),
        "aggregate_execute_calls": aggregate_counter.count,
        "relation_bytes_before": {
            "total": relation_before[0],
            "table": relation_before[1],
            "indexes": relation_before[2],
        },
        "relation_bytes_after": {
            "total": relation_after[0],
            "table": relation_after[1],
            "indexes": relation_after[2],
        },
        "relation_bytes_delta": {
            "total": relation_after[0] - relation_before[0],
            "table": relation_after[1] - relation_before[1],
            "indexes": relation_after[2] - relation_before[2],
        },
        "explain": explain_row[0],
        "task_budget_seconds": {"soft": 3_500, "hard": 3_600},
    }
    print("DATA02_SCALE_METRICS=" + json.dumps(metrics, sort_keys=True))
