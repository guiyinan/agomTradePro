"""Two real PostgreSQL writers retain one first-recorded calendar identity."""

from collections.abc import Iterator
from queue import Queue
from threading import Barrier, Thread

import pytest
from django.db import close_old_connections, connection, connections

from apps.data_center.domain.exchange_calendar import ExchangeCalendarSnapshot
from apps.data_center.infrastructure.exchange_calendar_repository import (
    DjangoExchangeCalendarSnapshotRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
)
from tests.component.data_center.test_exchange_calendar_snapshot_repository import _candidate
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    if connection.vendor != "postgresql":
        pytest.skip("Calendar first-writer serialization requires PostgreSQL row locks")
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((RawPayloadModel, ExchangeCalendarSnapshotFactModel)):
            yield


def test_concurrent_first_write_returns_one_immutable_snapshot() -> None:
    """Concurrent retries must agree on the first ID, clock, and record digest."""

    candidate, _raw_repository = _candidate()
    ready = Barrier(2, timeout=10)
    results: Queue[tuple[int, ExchangeCalendarSnapshot | str]] = Queue()

    def save() -> None:
        close_old_connections()
        backend_pid = -1
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET statement_timeout = '10000ms'")
                cursor.execute("SELECT pg_backend_pid()")
                backend_pid = cursor.fetchone()[0]
            ready.wait()
            snapshot = DjangoExchangeCalendarSnapshotRepository().save(candidate)
            results.put((backend_pid, snapshot))
        except Exception as error:
            results.put((backend_pid, f"{type(error).__name__}: {error}"))
        finally:
            connections["default"].close()

    writers = [Thread(target=save, daemon=True) for _ in range(2)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=15)

    assert all(not writer.is_alive() for writer in writers)
    outcomes = [results.get(timeout=1) for _ in writers]
    assert len({pid for pid, _result in outcomes}) == 2
    snapshots = [result for _pid, result in outcomes]
    assert all(isinstance(result, ExchangeCalendarSnapshot) for result in snapshots), outcomes
    assert snapshots[0] == snapshots[1]
    assert ExchangeCalendarSnapshotFactModel.objects.count() == 1
    assert RawPayloadModel.objects.count() == 1
