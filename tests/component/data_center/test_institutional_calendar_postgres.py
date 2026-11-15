"""Real PostgreSQL races for immutable institutional-calendar versions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from django.db import connection, connections

from apps.data_center.domain.institutional_calendar import InstitutionalEvent
from apps.data_center.infrastructure.institutional_calendar_models import (
    InstitutionalCalendarEventModel,
)
from apps.data_center.infrastructure.institutional_calendar_repository import (
    DjangoInstitutionalCalendarRepository,
)
from core.exceptions import DataValidationError
from tests.component.data_center.test_institutional_calendar_repository import _event
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = [
    pytest.mark.django_db(transaction=True, available_apps=("apps.data_center",)),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="native PostgreSQL required"),
]


@pytest.mark.parametrize("conflicting_content", (False, True))
def test_concurrent_first_revision_has_one_immutable_winner(conflicting_content: bool) -> None:
    """Concurrent replay returns one winner; conflicting content never overwrites it."""
    assert_native_postgres_test_database(expected_name="cal02_institutional_calendar_qa")
    first = _event()
    second = replace(first, title="Conflicting concurrent title") if conflicting_content else first
    barrier = Barrier(2)

    def append(event: InstitutionalEvent) -> InstitutionalEvent | str:
        connections.close_all()
        try:
            barrier.wait(timeout=15)
            try:
                return DjangoInstitutionalCalendarRepository().append(event)
            except DataValidationError as error:
                return error.code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(append, event) for event in (first, second)]
        results = [future.result(timeout=30) for future in futures]

    persisted = DjangoInstitutionalCalendarRepository().get_version(first.event_id, 1)
    assert InstitutionalCalendarEventModel.objects.count() == 1
    if conflicting_content:
        winners = [result for result in results if isinstance(result, InstitutionalEvent)]
        assert len(winners) == 1 and persisted == winners[0]
        assert results.count("INSTITUTIONAL_EVENT_IDENTITY_CONFLICT") == 1
    else:
        assert results == [first, first]
        assert persisted == first
