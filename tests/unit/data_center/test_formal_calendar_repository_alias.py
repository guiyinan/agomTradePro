"""Stable error boundary for an unavailable formal Calendar database alias."""

from datetime import UTC, datetime
from unittest.mock import create_autospec

import pytest

from apps.data_center.application.calendar_formal_publication_audit_port import (
    CalendarFormalPublicationAuditPort,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    ReadCurrentExchangeCalendarPublicationQuery,
)
from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
    DjangoFormalExchangeCalendarPublicationRepository,
)
from core.exceptions import DataFetchError


def test_missing_database_alias_raises_stable_calendar_storage_error() -> None:
    """An unconfigured alias cannot leak Django's connection-registry exception."""

    audit = create_autospec(CalendarFormalPublicationAuditPort, instance=True)
    audit.database_alias = "default"
    repository = DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit,
        using="formal-calendar-unconfigured-alias",
    )
    query = ReadCurrentExchangeCalendarPublicationQuery(
        dataset_key="test.exchange_calendar",
        exchange="SSE",
        as_of=datetime.now(UTC),
    )

    with pytest.raises(DataFetchError) as failure:
        repository.read_current(query)

    assert failure.value.code == "CALENDAR_FORMAL_DATABASE_UNAVAILABLE"
