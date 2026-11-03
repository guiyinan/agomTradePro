"""Composition root for the isolated calendar catalog bootstrap use case."""

from apps.data_center.application.calendar_catalog_bootstrap import (
    CreateCalendarCatalogBootstrapUseCase,
)
from apps.data_center.infrastructure.calendar_catalog_bootstrap_repository import (
    DjangoCalendarCatalogBootstrapRepository,
)


def build_calendar_catalog_bootstrap_use_case(
    using: str = "default",
) -> CreateCalendarCatalogBootstrapUseCase:
    """Build the create-only calendar catalog use case for one database alias."""

    return CreateCalendarCatalogBootstrapUseCase(
        DjangoCalendarCatalogBootstrapRepository(using=using)
    )


__all__ = ["build_calendar_catalog_bootstrap_use_case"]
