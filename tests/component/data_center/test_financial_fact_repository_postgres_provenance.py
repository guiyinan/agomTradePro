"""Opt-in PostgreSQL round-trip cases for the DATA-02 financial carrier."""

from __future__ import annotations

import os
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import unquote, urlsplit

import pytest
from django.db import connections
from django.db.utils import load_backend

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_source_evidence import FinancialFactSourceEvidence
from apps.data_center.infrastructure.financial_fact_repository import (
    FinancialFactProvenanceConflictError,
    FinancialFactRepository,
)
from apps.data_center.infrastructure.models import FinancialFactModel

_POSTGRES_FLAG = "AGOM_EVID06_POSTGRES_TEST"
_POSTGRES_URL = "AGOM_EVID06_POSTGRES_TEST_DATABASE_URL"
_DATABASE_NAME = "evid06_authority_test"
_ASSET_CODE = "000001.SZ"
_PERIOD_END = date(2026, 6, 30)
_ANNOUNCED_AT = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
_AVAILABLE_AT = _ANNOUNCED_AT + timedelta(minutes=5)
_SOURCE_HASH = "a" * 64


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
        "connect_timeout": 30,
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
            "connect_timeout": 30,
            "sslmode": "disable",
            "gssencmode": "disable",
        },
    )
    wrapper = load_backend(database_settings["ENGINE"]).DatabaseWrapper(
        database_settings,
        alias="default",
    )
    created = False
    with django_db_blocker.unblock():
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


@pytest.fixture(autouse=True)
def _clear_financial_rows(_financial_postgres_schema) -> Iterator[None]:
    """Keep the two cases row-isolated while the module owns one table."""

    FinancialFactModel.objects.all().delete()
    yield
    FinancialFactModel.objects.all().delete()


def _evidence() -> FinancialFactSourceEvidence:
    """Build one complete three-field source witness."""

    return FinancialFactSourceEvidence(
        announced_at=_ANNOUNCED_AT,
        source_record_id="pg-vendor-record-1",
        raw_payload_hash=_SOURCE_HASH,
    )


def _fact(
    *, metric_code: str, value: float, evidence: FinancialFactSourceEvidence | None = None
) -> FinancialFact:
    """Build one financial fact with explicit source timing and optional witness."""

    return FinancialFact(
        asset_code=_ASSET_CODE,
        period_end=_PERIOD_END,
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code=metric_code,
        value=value,
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 13),
        available_at=_AVAILABLE_AT,
        source_evidence=evidence,
    )


def _direct_model_row(*, metric_code: str, value: float) -> FinancialFactModel:
    """Persist one direct float model value as the backend storage oracle."""

    row = FinancialFactModel.objects.create(
        asset_code=_ASSET_CODE,
        period_end=_PERIOD_END,
        period_type="quarterly",
        metric_code=metric_code,
        value=value,
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 13),
        available_at=_AVAILABLE_AT,
    )
    row.refresh_from_db()
    return row


def test_financial_repository_round_trip_and_replay_count_on_postgresql() -> None:
    """PostgreSQL storage matches the direct writer and replay performs no write."""

    oracle = _direct_model_row(metric_code="pg_oracle", value=12.34525)
    fact = _fact(metric_code="pg_repository", value=12.34525, evidence=_evidence())
    repository = FinancialFactRepository()

    assert repository.bulk_upsert([fact]) == 1
    row = FinancialFactModel.objects.get(metric_code="pg_repository")
    assert row.value == oracle.value
    assert row.announced_at == _ANNOUNCED_AT
    assert row.source_record_id == "pg-vendor-record-1"
    assert row.raw_payload_hash == _SOURCE_HASH
    fetched_at = row.fetched_at

    assert repository.bulk_upsert([fact]) == 0
    row.refresh_from_db()
    assert row.value == oracle.value
    assert row.fetched_at == fetched_at


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(12.03125, id="positive_12_03125"),
        pytest.param(-12.03125, id="negative_12_03125"),
        pytest.param(12.34505, id="positive_12_34505"),
        pytest.param(12.34525, id="positive_12_34525"),
        pytest.param(12.34535, id="positive_12_34535"),
    ],
)
def test_repository_float_ties_match_direct_postgresql_writer(value: float) -> None:
    """Every tie value follows the unchanged ORM writer and replays as a no-op."""

    oracle = _direct_model_row(metric_code="pg_tie_oracle", value=value)
    fact = _fact(metric_code="pg_tie_repository", value=value, evidence=_evidence())
    repository = FinancialFactRepository()

    assert repository.bulk_upsert([fact]) == 1
    row = FinancialFactModel.objects.get(metric_code="pg_tie_repository")
    assert row.value == oracle.value
    fetched_at = row.fetched_at
    assert row.announced_at == _ANNOUNCED_AT
    assert row.source_record_id == "pg-vendor-record-1"
    assert row.raw_payload_hash == _SOURCE_HASH

    assert repository.bulk_upsert([fact]) == 0
    row.refresh_from_db()
    assert row.value == oracle.value
    assert row.fetched_at == fetched_at


def test_financial_repository_stale_witness_rolls_back_postgresql_batch() -> None:
    """A stale protected row blocks the batch before its new row can remain."""

    protected = _direct_model_row(metric_code="pg_protected", value=100.0)
    protected.announced_at = _ANNOUNCED_AT
    protected.source_record_id = "pg-old-record"
    protected.raw_payload_hash = _SOURCE_HASH
    protected.save(update_fields=["announced_at", "source_record_id", "raw_payload_hash"])
    replacement = _fact(metric_code="pg_protected", value=101.0)
    new_fact = _fact(metric_code="pg_new", value=1.0)

    with pytest.raises(FinancialFactProvenanceConflictError, match="stale"):
        FinancialFactRepository().bulk_upsert([replacement, new_fact])

    protected.refresh_from_db()
    assert protected.value == Decimal("100.0000")
    assert protected.raw_payload_hash == _SOURCE_HASH
    assert not FinancialFactModel.objects.filter(metric_code="pg_new").exists()
