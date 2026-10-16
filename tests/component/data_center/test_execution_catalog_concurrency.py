"""Real PostgreSQL race for the immutable execution TTL of a first version."""

from collections.abc import Iterator
from queue import Queue
from threading import Barrier, Thread

import pytest
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    models,
    transaction,
)
from django.db.models import QuerySet

from apps.data_center.domain.contracts import DatasetContract, DatasetFieldContract, DatasetKey
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.catalog_runtime_repositories import DatasetContractRepository
from apps.data_center.infrastructure.publication_fact_write_lock import (
    acquire_execution_catalog_activation_lock,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL first-writer race requires two real PostgreSQL connections")
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((DatasetContractModel,)):
            yield


def _contract(ttl: int) -> DatasetContract:
    return DatasetContract(
        key=DatasetKey("fixture.execution.catalog.race", "1", "1"),
        owner="fixture-only",
        frequency="intraday",
        decision_critical=True,
        fields=(
            DatasetFieldContract(
                name="snapshot_at",
                value_type="datetime",
                unit=None,
                nullable=False,
                zero_allowed=False,
            ),
        ),
        execution_freshness_seconds=ttl,
    )


def test_concurrent_first_creation_cannot_overwrite_execution_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both writers miss the row; exactly one TTL becomes the immutable winner."""

    barrier = Barrier(2, timeout=10)
    original_first = QuerySet.first

    def synchronized_first(query: QuerySet[models.Model]) -> models.Model | None:
        row = original_first(query)
        if query.model is DatasetContractModel and row is None:
            barrier.wait()
        return row

    monkeypatch.setattr(QuerySet, "first", synchronized_first)
    results: Queue[tuple[str, int]] = Queue()

    def write(ttl: int) -> None:
        close_old_connections()
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET statement_timeout = '10000ms'")
            try:
                saved = DatasetContractRepository().save(_contract(ttl))
            except ValueError as error:
                if "requires a new contract version" not in str(error):
                    raise
                results.put(("immutable_conflict", ttl))
            except DatabaseError:
                results.put(("unexpected_database_failure", ttl))
            else:
                assert saved.execution_freshness_seconds == ttl
                results.put(("created", ttl))
        finally:
            connections["default"].close()

    writers = [Thread(target=write, args=(ttl,), daemon=True) for ttl in (5, 7)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=15)
    assert all(not writer.is_alive() for writer in writers)
    outcomes = [results.get(timeout=1) for _ in writers]
    assert sorted(status for status, _ttl in outcomes) == ["created", "immutable_conflict"]
    winner = next(ttl for status, ttl in outcomes if status == "created")
    assert DatasetContractModel._default_manager.count() == 1
    stored = DatasetContractRepository().get_active_for_execution("fixture.execution.catalog.race")
    assert stored is not None
    assert stored.execution_freshness_seconds == winner


def test_execution_activation_catalog_lock_blocks_active_contract_phantom() -> None:
    """The activation table fence blocks a direct active-row insert until commit."""

    started = Barrier(2, timeout=10)
    allow_second_insert = Barrier(2, timeout=10)
    outcomes: Queue[str] = Queue()

    def insert_active_contract() -> None:
        close_old_connections()
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET lock_timeout = '250ms'")
            started.wait()
            try:
                with transaction.atomic():
                    DatasetContractModel.objects.create(
                        dataset_key="fixture.execution.catalog.phantom",
                        contract_version="1",
                        schema_version="1",
                        owner="fixture-only",
                        frequency="intraday",
                        decision_critical=True,
                        fields=[{"name": "snapshot_at", "value_type": "datetime"}],
                        execution_freshness_seconds=5,
                        active=True,
                    )
            except DatabaseError:
                outcomes.put("blocked")
            else:
                outcomes.put("unexpectedly_inserted")
                return

            allow_second_insert.wait()
            DatasetContractModel.objects.create(
                dataset_key="fixture.execution.catalog.phantom",
                contract_version="1",
                schema_version="1",
                owner="fixture-only",
                frequency="intraday",
                decision_critical=True,
                fields=[{"name": "snapshot_at", "value_type": "datetime"}],
                execution_freshness_seconds=5,
                active=True,
            )
            outcomes.put("inserted_after_release")
        finally:
            connections["default"].close()

    writer = Thread(target=insert_active_contract, daemon=True)
    with transaction.atomic():
        acquire_execution_catalog_activation_lock()
        writer.start()
        started.wait()
        # The worker reaches its bounded lock timeout while this transaction holds SHARE.
        writer.join(timeout=2)
        assert writer.is_alive()

    allow_second_insert.wait()
    writer.join(timeout=10)
    assert not writer.is_alive()
    assert outcomes.get(timeout=1) == "blocked"
    assert outcomes.get(timeout=1) == "inserted_after_release"
    assert (
        DatasetContractModel.objects.filter(
            dataset_key="fixture.execution.catalog.phantom",
            active=True,
        ).count()
        == 1
    )
