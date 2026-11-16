"""Typed adapter from raw catalog APIs to the verifier's rich resolution port."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from apps.data_center.application.financial_numeric_catalog import (
    FinancialNumericSourceCatalogRepositoryPort,
)
from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericCatalogEntrySnapshotReadPort,
    FinancialNumericSourceQualificationCatalogPort,
    FinancialNumericSourceQualificationResolution,
    FinancialNumericVerificationContext,
    FinancialNumericVerificationPurpose,
)
from apps.data_center.domain.financial_numeric_catalog import (
    FinancialNumericCatalogResolutionPurpose,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceQualification,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_FINANCIAL_NUMERIC_ENDPOINTS,
)


class FinancialNumericQualificationCatalogAdapter(FinancialNumericSourceQualificationCatalogPort):
    """Adapt the qualification-only repository API without inventing DB metadata.

    Construct the production instance through
    ``DjangoFinancialNumericSourceQualificationCatalogAdapter`` so the catalog
    repository and entry snapshot reader share the capture repository's one
    explicit database alias. This adapter itself never starts or ends a UOW.
    """

    def __init__(
        self,
        repository: FinancialNumericSourceCatalogRepositoryPort,
        snapshot_reader: FinancialNumericCatalogEntrySnapshotReadPort,
    ) -> None:
        """Bind the exact catalog resolver and its persisted-metadata reader."""

        if repository is None or snapshot_reader is None:
            raise TypeError("catalog resolver and persisted snapshot reader are required")
        self._repository = repository
        self._snapshot_reader = snapshot_reader

    def resolve_exact(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        verification_context: FinancialNumericVerificationContext,
    ) -> FinancialNumericSourceQualificationResolution | None:
        """Resolve an exact Main or Balance contract and persisted event metadata.

        All current purposes use the repository's lock-retaining UOW resolver.
        Only an explicit point-in-time purpose uses the unlocked as-of resolver.
        The adapter never starts or ends the caller's current-use transaction,
        and ``known_at`` is never derived from a fact timestamp.
        """

        if (
            type(contract_identity) is not str
            or not contract_identity
            or contract_identity != contract_identity.strip()
            or type(endpoint) is not str
            or endpoint not in AKSHARE_FINANCIAL_NUMERIC_ENDPOINTS
            or type(source_response_completed_at) is not datetime
            or not isinstance(source_context, Mapping)
            or any(type(key) is not str for key in source_context)
            or type(verification_context) is not FinancialNumericVerificationContext
        ):
            return None
        if verification_context.purpose is FinancialNumericVerificationPurpose.POINT_IN_TIME_READ:
            qualification = self._repository.resolve_exact(
                contract_identity,
                endpoint=endpoint,
                source_response_completed_at=source_response_completed_at,
                source_context=source_context,
                known_at=verification_context.known_at,
            )
        else:
            qualification = self._repository.resolve_exact_in_uow(
                contract_identity,
                endpoint=endpoint,
                source_response_completed_at=source_response_completed_at,
                source_context=source_context,
                purpose=_catalog_purpose(verification_context.purpose),
                known_at=verification_context.known_at,
            )
        if (
            type(qualification) is not FinancialNumericSourceQualification
            or qualification.endpoint != endpoint
        ):
            return None
        if (
            qualification.contract.identity != contract_identity
            or qualification.contract.origin != "native"
            or not qualification.matches_source_context(source_context)
        ):
            return None
        entry = self._snapshot_reader.read_exact_entry(
            qualification,
            known_at=verification_context.known_at,
        )
        if entry is None or entry.qualification != qualification:
            return None
        try:
            resolution = FinancialNumericSourceQualificationResolution(entry=entry)
        except (TypeError, ValueError):
            return None
        if not qualification.is_eligible_at(
            known_at=verification_context.known_at,
            source_response_completed_at=source_response_completed_at,
            recorded_at=resolution.recorded_at,
            approved_at=resolution.approved_at,
            revoked_at=resolution.revoked_at,
        ):
            return None
        return resolution


def _catalog_purpose(
    purpose: FinancialNumericVerificationPurpose,
) -> FinancialNumericCatalogResolutionPurpose:
    """Map every current-use purpose to the matching catalog UOW fence."""

    if purpose is FinancialNumericVerificationPurpose.CURRENT_READ:
        return FinancialNumericCatalogResolutionPurpose.CURRENT_READ
    if purpose is FinancialNumericVerificationPurpose.CURRENT_WRITE:
        return FinancialNumericCatalogResolutionPurpose.CURRENT_WRITE
    if purpose is FinancialNumericVerificationPurpose.CURRENT_PUBLICATION:
        return FinancialNumericCatalogResolutionPurpose.CURRENT_PUBLICATION
    raise ValueError("point-in-time purpose does not use the current UOW resolver")


__all__ = ["FinancialNumericQualificationCatalogAdapter"]
