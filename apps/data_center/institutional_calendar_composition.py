"""Public read-only composition for exact institutional-calendar queries."""

from __future__ import annotations

from apps.data_center.application.institutional_calendar_query import (
    QueryInstitutionalCalendarUseCase,
)
from apps.data_center.infrastructure.institutional_calendar_repository import (
    DjangoInstitutionalCalendarRepository,
)


def make_institutional_calendar_query(
    *, using: str = "default", timezone_name: str
) -> QueryInstitutionalCalendarUseCase:
    """Bind the exact-version repository, database alias, and explicit local timezone."""

    return QueryInstitutionalCalendarUseCase(
        DjangoInstitutionalCalendarRepository(using=using), timezone_name=timezone_name
    )


__all__ = ["make_institutional_calendar_query"]
