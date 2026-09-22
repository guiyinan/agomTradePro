"""Opt-in PostgreSQL concurrency proof for financial natural-key insert order."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from urllib.parse import unquote, urlsplit
from uuid import UUID

import pytest
from django.db import close_old_connections, connections
from django.db.utils import load_backend

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import (
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.infrastructure import financial_fact_write_guard as guard
from apps.data_center.infrastructure.models import FinancialFactModel

_POSTGRES_FLAG = "AGOM_EVID06_POSTGRES_TEST"
_POSTGRES_URL = "AGOM_EVID06_POSTGRES_TEST_DATABASE_URL"
_RESULT_ENV = "AGOM_FINANCIAL_PG_CONCURRENCY_RESULT"
_DATABASE_NAME = "evid06_authority_test"
_ASSET_CODE = "000001.SZ"
_PERIOD_END = date(2026, 6, 30)


@dataclass(frozen=True)
class _WorkerResult:
    """Sanitized identity and write result returned by one PostgreSQL worker."""

    backend_pid: int
    database_name: str
    vendor: str
    stored_count: int


def _credentials() -> dict[str, object]:
    """Read the already-bound loopback target without exposing its password."""

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
        "connect_timeout": 10,
        "sslmode": "disable",
        "gssencmode": "disable",
    }


def _database_observation(wrapper) -> tuple[str, int, int]:
    """Return database identity, public-table count, and other client count."""

    with wrapper.cursor() as cursor:
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
def _financial_postgres_schema(django_db_blocker) -> Iterator[None]:
    """Create and remove only the financial fact table in the empty test DB."""

    credentials = _credentials()
    original = connections["default"]
    database_settings = deepcopy(original.settings_dict)
    database_settings.update(
        ENGINE="django.db.backends.postgresql",
        NAME=_DATABASE_NAME,
        USER=credentials["user"],
        PASSWORD=credentials["password"],
        HOST=credentials["host"],
        PORT=str(credentials["port"]),
        CONN_MAX_AGE=0,
        OPTIONS={
            "connect_timeout": 10,
            "sslmode": "disable",
            "gssencmode": "disable",
        },
    )
    wrapper = load_backend(database_settings["ENGINE"]).DatabaseWrapper(
        database_settings,
        alias="default",
    )
    created = False
    original_database_settings = deepcopy(connections.databases["default"])
    with django_db_blocker.unblock():
        # ``connections["default"]`` is thread-local.  Publish the same
        # isolated PostgreSQL settings so each worker lazily creates a fresh
        # PostgreSQL wrapper instead of falling back to the SQLite test DB.
        connections.databases["default"] = database_settings
        connections["default"] = wrapper
        try:
            if wrapper.vendor != "postgresql":
                pytest.fail("financial fixture resolved a non-PostgreSQL backend")
            database_name, table_count, other_clients = _database_observation(wrapper)
            assert database_name == _DATABASE_NAME
            assert table_count == 0
            assert other_clients == 0
            with wrapper.schema_editor() as editor:
                editor.create_model(FinancialFactModel)
            created = True
            assert wrapper.introspection.table_names() == [FinancialFactModel._meta.db_table]
            yield
        finally:
            if created:
                wrapper.rollback()
                with wrapper.schema_editor() as editor:
                    editor.delete_model(FinancialFactModel)
                database_name, table_count, other_clients = _database_observation(wrapper)
                assert database_name == _DATABASE_NAME
                assert table_count == 0
                assert other_clients == 0
            wrapper.close()
            connections["default"] = original
            connections.databases["default"] = original_database_settings


@pytest.fixture(autouse=True)
def _clear_financial_rows(_financial_postgres_schema) -> Iterator[None]:
    """Keep the concurrency case isolated to one empty table."""

    FinancialFactModel.objects.all().delete()
    yield
    close_old_connections()
    FinancialFactModel.objects.all().delete()


def _fact(metric_code: str) -> FinancialFact:
    """Build one unambiguous new natural key for the concurrent writers."""

    announced_at = datetime(2026, 9, 14, 8, tzinfo=UTC)
    available_at = announced_at + timedelta(minutes=5)
    source_record_id = "pg-concurrency-row-1"
    body_sha256 = "e" * 64
    response = FinancialResponseEvidence(
        body_sha256=body_sha256,
        body_size_bytes=128,
        response_completed_at=available_at + timedelta(minutes=1),
        request_scope=FinancialRequestScope(
            provider_name="provider-main",
            dataset_key="equity.financial.fact",
            asset_code=_ASSET_CODE,
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=(_ASSET_CODE,),
            period_ends=(_PERIOD_END,),
            row_count=1,
        ),
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    return FinancialFact(
        asset_code=_ASSET_CODE,
        period_end=_PERIOD_END,
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code=metric_code,
        value=123.45,
        unit="CNY",
        source="provider-main",
        report_date=_PERIOD_END,
        available_at=available_at,
        source_evidence=FinancialFactSourceEvidence(
            announced_at=announced_at,
            source_record_id=source_record_id,
            raw_payload_hash=body_sha256,
        ),
        decision_evidence=FinancialFactDecisionEvidence(
            artifact_reference=FinancialResponseArtifactRef(
                capture_id=UUID("60000000-0000-4000-8000-000000000001"),
                location="financial-response/postgres-concurrency.bin",
                evidence=response,
                format_version="financial-response-artifact.v1",
                encryption_algorithm="fernet",
                encryption_key_ref="config_center.data02.test-key",
                encryption_key_version="v1",
            ),
            native_asset_code=_ASSET_CODE,
            native_period_end=_PERIOD_END,
            native_row_id=source_record_id,
        ),
    )


def _run_batch(facts: list[FinancialFact]) -> _WorkerResult:
    """Run one write and report its real connection identity and count."""

    close_old_connections()
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '2s'")
            cursor.execute("SET statement_timeout = '15s'")
            cursor.execute("SELECT pg_backend_pid(), current_database()")
            identity = cursor.fetchone()
        if identity is None:
            raise AssertionError("PostgreSQL connection identity returned no row")
        backend_pid = int(identity[0])
        database_name = str(identity[1])
        vendor = str(connection.vendor)
        stored_count = guard.bulk_upsert_financial_facts(facts)
        return _WorkerResult(
            backend_pid=backend_pid,
            database_name=database_name,
            vendor=vendor,
            stored_count=stored_count,
        )
    finally:
        connection.close()


def _write_result(
    results: list[_WorkerResult],
    readback_rows: int,
) -> None:
    """Optionally persist sanitized concurrency evidence for the parent collector."""

    destination = os.environ.get(_RESULT_ENV, "").strip()
    if not destination:
        return
    payload: dict[str, object] = {
        "schema": "data02-financial-natural-key-concurrency.v1",
        "result_at_utc": datetime.now(UTC).isoformat(),
        "workers": [asdict(result) for result in results],
        "backend_pids": [result.backend_pid for result in results],
        "stored_counts": [result.stored_count for result in results],
        "readback_rows": readback_rows,
    }
    Path(destination).write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def test_reversed_new_key_batches_complete_without_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two real PostgreSQL writers converge when their new keys are reversed."""

    barrier = Barrier(2)
    original_insert = guard._insert_new_batch

    def synchronized_insert(facts: list[FinancialFact]) -> int:
        """Align both writers immediately before their first insert attempt."""

        if facts:
            barrier.wait(timeout=8)
        return original_insert(facts)

    monkeypatch.setattr(guard, "_insert_new_batch", synchronized_insert)
    facts = [_fact("metric_b"), _fact("metric_a")]

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="data02-pg") as executor:
        futures = [
            executor.submit(_run_batch, list(facts)),
            executor.submit(_run_batch, list(reversed(facts))),
        ]
        try:
            results = [future.result(timeout=25) for future in futures]
        except FutureTimeoutError:
            # ``Future.result(timeout=...)`` only bounds observation.  The
            # executor context still joins running threads; root's external
            # 300-second wrapper owns the final kill/reap boundary.
            pytest.fail("concurrent financial insert exceeded the bounded join timeout")
        except BaseException:
            raise

    assert len(results) == 2
    assert all(result.backend_pid > 0 for result in results)
    assert len({result.backend_pid for result in results}) == 2
    assert all(result.vendor == "postgresql" for result in results)
    assert all(result.database_name == _DATABASE_NAME for result in results)
    assert sorted(result.stored_count for result in results) == [0, 2]
    readback_rows = FinancialFactModel.objects.count()
    _write_result(results, readback_rows)
    assert readback_rows == 2
    assert set(FinancialFactModel.objects.values_list("metric_code", flat=True)) == {
        "metric_a",
        "metric_b",
    }
