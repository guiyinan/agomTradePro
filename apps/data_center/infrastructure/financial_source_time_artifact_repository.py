"""Infrastructure facade for contract-neutral financial source-time retention."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from uuid import UUID

from apps.data_center.application.financial_source_time_artifact import (
    FinancialSourceTimeArtifactAuditPort,
    FinancialSourceTimeArtifactOrphan,
    FinancialSourceTimeArtifactRetention,
    RetainFinancialSourceTimeArtifactUseCase,
)
from apps.data_center.domain.financial_source_time_evidence import (
    FinancialSourceTimeArtifactRef,
)
from apps.data_center.infrastructure.financial_source_time_body_store import (
    FinancialSourceTimeBodyStore,
)


class FinancialSourceTimeArtifactRepository:
    """Compose encrypted source-time body storage with append-only RawAudit."""

    def __init__(
        self,
        body_store: FinancialSourceTimeBodyStore,
        audit_repository: FinancialSourceTimeArtifactAuditPort,
    ) -> None:
        """Bind explicitly configured infrastructure ports."""

        self._body_store = body_store
        self._retainer = RetainFinancialSourceTimeArtifactUseCase(
            body_store=body_store,
            audit_repository=audit_repository,
        )

    def retain(
        self,
        *,
        capture_id: UUID,
        provider_name: str,
        provider_id: int,
        requested_asset_code: str,
        requested_announcement_date: date,
        body: bytes,
        response_completed_at: datetime,
        response_row_count: int,
        request_params: Mapping[str, object],
        parser_version: str,
    ) -> FinancialSourceTimeArtifactRetention:
        """Retain provider-native bytes without interpreting time semantics."""

        reference = self._body_store.build_reference(
            capture_id=capture_id,
            provider_name=provider_name,
            requested_asset_code=requested_asset_code,
            requested_announcement_date=requested_announcement_date,
            body=body,
            response_completed_at=response_completed_at,
            response_row_count=response_row_count,
        )
        return self._retainer.execute(
            reference=reference,
            body=body,
            provider_id=provider_id,
            request_params=request_params,
            parser_version=parser_version,
        )

    def read(self, reference: FinancialSourceTimeArtifactRef) -> bytes:
        """Read exact authenticated provider-native bytes."""

        return self._body_store.read(reference)

    def inspect_orphan(
        self,
        reference: FinancialSourceTimeArtifactRef,
    ) -> FinancialSourceTimeArtifactOrphan:
        """Expose verified body/audit cardinality for reconciliation."""

        return self._retainer.inspect_orphan(reference)


__all__ = ["FinancialSourceTimeArtifactRepository"]
