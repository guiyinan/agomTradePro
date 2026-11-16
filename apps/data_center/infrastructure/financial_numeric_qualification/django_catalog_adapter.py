"""Compose the verifier adapter with the real numeric catalog repositories."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericSourceQualificationCatalogPort,
    FinancialNumericSourceQualificationResolution,
    FinancialNumericVerificationContext,
)
from apps.data_center.infrastructure.financial_numeric_catalog_capture_repository import (
    DjangoFinancialNumericSourceCaptureRepository,
)
from apps.data_center.infrastructure.financial_numeric_catalog_repository import (
    DjangoFinancialMetricSourceCatalogRepository,
)

from .catalog_adapter import FinancialNumericQualificationCatalogAdapter
from .django_snapshot_reader import DjangoFinancialNumericCatalogEntrySnapshotReader


class DjangoFinancialNumericSourceQualificationCatalogAdapter(
    FinancialNumericSourceQualificationCatalogPort
):
    """Expose the verifier port over one exact alias and the real catalog fence API.

    Construction binds the catalog repository and metadata reader to the
    capture repository's public database alias. The adapter does not create a
    transaction. Current write and Publication callers must retain their own
    PostgreSQL READ COMMITTED outer transaction through the fact/Publication
    commit.
    """

    def __init__(
        self,
        *,
        capture_repository: DjangoFinancialNumericSourceCaptureRepository,
        using: str,
    ) -> None:
        """Compose resolver and metadata reader with the same checked alias."""

        if type(capture_repository) is not DjangoFinancialNumericSourceCaptureRepository:
            raise TypeError("a Django retained-capture repository is required")
        if type(using) is not str or not using or using != using.strip() or len(using) > 128:
            raise ValueError("database alias must be explicit bounded text")
        if capture_repository.database_alias != using:
            raise ValueError("capture and catalog adapter must use one database alias")
        repository = DjangoFinancialMetricSourceCatalogRepository(
            capture_repository=capture_repository,
            using=using,
        )
        snapshot_reader = DjangoFinancialNumericCatalogEntrySnapshotReader(using=using)
        self._adapter = FinancialNumericQualificationCatalogAdapter(
            repository,
            snapshot_reader,
        )
        self._using = using

    @property
    def database_alias(self) -> str:
        """Expose the single alias shared by resolver and metadata reader."""

        return self._using

    def resolve_exact(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        verification_context: FinancialNumericVerificationContext,
    ) -> FinancialNumericSourceQualificationResolution | None:
        """Resolve qualification and real metadata using the caller's clocks/UOW."""

        return self._adapter.resolve_exact(
            contract_identity,
            endpoint=endpoint,
            source_response_completed_at=source_response_completed_at,
            source_context=source_context,
            verification_context=verification_context,
        )


__all__ = ["DjangoFinancialNumericSourceQualificationCatalogAdapter"]
