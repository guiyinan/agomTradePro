"""Native PostgreSQL permission ordering for QMT batch ingestion."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from datetime import timezone as datetime_timezone
from decimal import Decimal
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import DEFAULT_DB_ALIAS, close_old_connections, connection, connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils import timezone

from apps.data_center.application.qmt_bridge import BatchReceipt, QmtBridgeService
from apps.data_center.domain.qmt_bridge import BridgeBatch, BridgeSample
from apps.data_center.domain.qmt_daily_status import (
    BridgeDailyStatusBatch,
    BridgeDailyStatusSample,
)
from apps.data_center.infrastructure.models import PriceBarModel, QuoteSnapshotModel
from apps.data_center.infrastructure.qmt_bridge_models import QmtBridgeBatchModel
from apps.data_center.infrastructure.qmt_bridge_repository import QmtBridgeRepository
from core.exceptions import AuthorizationError
from tests.integration.data_center import test_qmt_bridge as bridge_contract
from tests.integration.data_center.test_qmt_bridge import approve
from tests.support.native_postgres_database import (
    assert_native_postgres_test_database,
)
from tests.support.native_postgres_database import (  # noqa: F401
    native_postgres_test_database as _native_postgres_test_database_fixture,
)

_CHINA_TIMEZONE = datetime_timezone(timedelta(hours=8))
_LOCK_WAIT_SECONDS = 6.0
_THREAD_TIMEOUT_SECONDS = 15.0
setup_bridge = bridge_contract.setup_bridge
isolated_bridge_cache = bridge_contract.isolated_bridge_cache

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="QMT owner-row lock ordering requires Native PostgreSQL",
    ),
]


@pytest.fixture(scope="session")
def django_db_setup(native_postgres_test_database: str) -> str:
    """Use the configured isolated PostgreSQL database and no implicit fallback."""

    return native_postgres_test_database


@pytest.fixture(autouse=True)
def _require_migrated_native_database(django_db_use_migrations: bool) -> None:
    """Refuse SQLite or unmigrated schemas before exercising row-level locks."""

    if not django_db_use_migrations:
        pytest.skip("QMT permission locks require the migrated Native test database")
    if connection.vendor != "postgresql":
        pytest.skip("QMT permission locks require PostgreSQL")
    assert_native_postgres_test_database()


def _daily_status_batch() -> BridgeDailyStatusBatch:
    """Build one completed status row using the fixed China-local market date."""

    collected_at = timezone.now()
    day = collected_at.astimezone(_CHINA_TIMEZONE).date() - timedelta(days=2)
    return BridgeDailyStatusBatch(
        batch_id=str(uuid4()),
        kind="daily_status",
        schema_version="qmt-native-daily-status.v1",
        collected_at=collected_at,
        request_start=day,
        request_end=day,
        samples=(BridgeDailyStatusSample("510300.SH", day, 1),),
    )


def _price_batch(kind: str) -> BridgeBatch:
    """Build a valid quote or daily bar to verify all ingest kinds share the guard."""

    collected_at = timezone.now()
    if kind == "bar":
        bar_date = collected_at.astimezone(_CHINA_TIMEZONE).date() - timedelta(days=2)
        observed_at = datetime(
            bar_date.year, bar_date.month, bar_date.day, 12, tzinfo=_CHINA_TIMEZONE
        )
    else:
        bar_date = None
        observed_at = collected_at - timedelta(seconds=1)
    sample = BridgeSample(
        asset_code="510300.SH",
        observed_at=observed_at,
        price=Decimal("3.5"),
        open=Decimal("3.4") if kind == "bar" else None,
        high=Decimal("3.6") if kind == "bar" else None,
        low=Decimal("3.3") if kind == "bar" else None,
        volume=Decimal("2"),
        amount=Decimal("7"),
        bar_date=bar_date,
    )
    return BridgeBatch(str(uuid4()), kind, collected_at, (sample,))


def _backend_pid(database: BaseDatabaseWrapper) -> int:
    """Read the current thread's PostgreSQL backend identity."""

    with database.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        row = cursor.fetchone()
    assert row is not None and type(row[0]) is int
    return int(row[0])


def _ingest_in_fresh_connection(
    *,
    binding_id: str,
    batch: BridgeDailyStatusBatch,
    backend_pids: list[int],
) -> BatchReceipt:
    """Run Application validation and repository persistence on an independent backend."""

    close_old_connections()
    database = connections[DEFAULT_DB_ALIAS]
    try:
        assert_native_postgres_test_database(database=database)
        with database.cursor() as cursor:
            cursor.execute("SET lock_timeout = '10000ms'")
            cursor.execute("SET statement_timeout = '15000ms'")
        backend_pids.append(_backend_pid(database))
        return QmtBridgeService(QmtBridgeRepository()).execute(binding_id, batch)
    finally:
        database.close()


def _deactivate_owner_in_fresh_connection(
    *, owner_id: int, started: Event, backend_pids: list[int]
) -> int:
    """Commit an owner deactivation through its own PostgreSQL connection."""

    close_old_connections()
    database = connections[DEFAULT_DB_ALIAS]
    try:
        assert_native_postgres_test_database(database=database)
        with database.cursor() as cursor:
            cursor.execute("SET lock_timeout = '10000ms'")
        backend_pid = _backend_pid(database)
        backend_pids.append(backend_pid)
        started.set()
        updated = get_user_model()._default_manager.filter(pk=owner_id).update(is_active=False)
        assert updated == 1
        return backend_pid
    finally:
        database.close()


def _wait_for_blocker(
    *, waiter_pid: int, expected_blocker_pid: int, waiter: Future[int]
) -> tuple[int, ...]:
    """Require PostgreSQL itself to report the ingest transaction blocking the UPDATE."""

    deadline = monotonic() + _LOCK_WAIT_SECONDS
    observed: tuple[int, ...] = ()
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_blocking_pids(%s)", [waiter_pid])
            row = cursor.fetchone()
        if row is not None and isinstance(row[0], (list, tuple)):
            observed = tuple(int(pid) for pid in row[0])
            if expected_blocker_pid in observed:
                return observed
        if waiter.done():
            waiter.result()
            break
        sleep(0.01)
    raise AssertionError(
        "PostgreSQL did not report the ingest backend blocking owner deactivation; "
        f"observed blocker PIDs were {observed}"
    )


def test_ingest_owner_lock_blocks_deactivation_until_status_receipt_commits(
    setup_bridge, monkeypatch
) -> None:
    """The ingest owner row lock orders a concurrent disable after its durable receipt."""

    assert_native_postgres_test_database()
    client, owner, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    assert type(owner.pk) is int
    batch = _daily_status_batch()
    store_entered = Event()
    release_store = Event()
    deactivate_started = Event()
    ingest_pids: list[int] = []
    deactivate_pids: list[int] = []
    original_store = QmtBridgeRepository._store_daily_status

    def hold_store_until_released(binding, status_batch: BridgeDailyStatusBatch) -> BatchReceipt:
        store_entered.set()
        if not release_store.wait(timeout=10):
            raise AssertionError("Test did not release the owner-locked ingestion")
        return original_store(binding, status_batch)

    monkeypatch.setattr(
        QmtBridgeRepository, "_store_daily_status", staticmethod(hold_store_until_released)
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        ingest = executor.submit(
            _ingest_in_fresh_connection,
            binding_id=pair["binding_id"],
            batch=batch,
            backend_pids=ingest_pids,
        )
        deactivate: Future[int] | None = None
        try:
            assert store_entered.wait(timeout=5), "Ingest did not acquire its database locks"
            deactivate = executor.submit(
                _deactivate_owner_in_fresh_connection,
                owner_id=owner.pk,
                started=deactivate_started,
                backend_pids=deactivate_pids,
            )
            assert deactivate_started.wait(timeout=5), "Deactivation backend did not start"
            assert len(ingest_pids) == len(deactivate_pids) == 1
            assert ingest_pids[0] != deactivate_pids[0]
            blockers = _wait_for_blocker(
                waiter_pid=deactivate_pids[0],
                expected_blocker_pid=ingest_pids[0],
                waiter=deactivate,
            )
            assert ingest_pids[0] in blockers
            assert get_user_model()._default_manager.get(pk=owner.pk).is_active is True
        finally:
            release_store.set()

        receipt = ingest.result(timeout=_THREAD_TIMEOUT_SECONDS)
        assert deactivate is not None
        assert deactivate.result(timeout=_THREAD_TIMEOUT_SECONDS) == deactivate_pids[0]

    assert receipt["batch_id"] == batch.batch_id
    assert QmtBridgeBatchModel.objects.filter(binding_id=pair["binding_id"]).count() == 1
    assert not QuoteSnapshotModel.objects.exists()
    assert not PriceBarModel.objects.exists()
    owner.refresh_from_db()
    assert owner.is_active is False


def test_committed_owner_deactivation_rejects_ingest_without_any_market_rows(
    setup_bridge,
) -> None:
    """A committed disable before any batch kind prevents all bridge writes."""

    assert_native_postgres_test_database()
    client, owner, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    owner.is_active = False
    owner.save(update_fields=["is_active"])
    service = QmtBridgeService(QmtBridgeRepository())
    for batch in (_daily_status_batch(), _price_batch("quote"), _price_batch("bar")):
        with pytest.raises(AuthorizationError):
            service.execute(pair["binding_id"], batch)

    assert not QmtBridgeBatchModel.objects.exists()
    assert not QuoteSnapshotModel.objects.exists()
    assert not PriceBarModel.objects.exists()
