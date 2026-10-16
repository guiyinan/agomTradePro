"""Verify immutable calendar response TTL under real first-writer competition."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection, connections, models
from django.db.models import QuerySet

from apps.data_center.domain.contracts import DatasetContract, DatasetFieldContract, DatasetKey
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.catalog_runtime_repositories import DatasetContractRepository
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


@pytest.fixture(autouse=True)
def _schema() -> Iterator[None]:
    if connection.vendor != "postgresql":
        pytest.skip("calendar response TTL first-writer race requires real PostgreSQL connections")
    with isolated_schema((DatasetContractModel,)):
        yield


def _contract(ttl: int) -> DatasetContract:
    return DatasetContract(
        key=DatasetKey("fixture.calendar.response-age.race", "1", "1"),
        owner="fixture-only",
        frequency="reference",
        decision_critical=False,
        fields=(
            DatasetFieldContract(
                name="calendar_date",
                value_type="date",
                unit=None,
                nullable=False,
                zero_allowed=False,
            ),
        ),
        execution_freshness_seconds=None,
        calendar_response_max_age_seconds=ttl,
    )


def test_concurrent_first_creation_cannot_replace_calendar_response_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both miss a version before inserting, and exactly one TTL survives."""

    rendezvous = Barrier(2, timeout=10)
    original_first = QuerySet.first

    def first_with_shared_miss(query: QuerySet[models.Model]) -> models.Model | None:
        value = original_first(query)
        if query.model is DatasetContractModel and value is None:
            rendezvous.wait()
        return value

    monkeypatch.setattr(QuerySet, "first", first_with_shared_miss)

    def write(ttl: int) -> tuple[str, int]:
        close_old_connections()
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET statement_timeout = '10000ms'")
            try:
                saved = DatasetContractRepository().save(_contract(ttl))
            except ValueError as error:
                if (
                    str(error)
                    != "calendar_response_max_age_seconds requires a new contract version"
                ):
                    raise
                return "immutable_conflict", ttl
            assert saved.calendar_response_max_age_seconds == ttl
            assert saved.execution_freshness_seconds is None
            return "created", ttl
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, ttl) for ttl in (5, 7)]
        outcomes = [future.result(timeout=20) for future in futures]

    assert sorted(status for status, _ in outcomes) == ["created", "immutable_conflict"]
    winner = next(ttl for status, ttl in outcomes if status == "created")
    assert DatasetContractModel._default_manager.count() == 1
    persisted = DatasetContractRepository().get_active_for_execution(
        "fixture.calendar.response-age.race"
    )
    assert persisted is not None
    assert persisted.calendar_response_max_age_seconds == winner
    assert persisted.execution_freshness_seconds is None
