"""Valuation and sector-membership synchronization use cases."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.data_center.application.dtos import (
    SyncResult,
    SyncSectorMembershipRequest,
    SyncValuationRequest,
)
from apps.data_center.domain.protocols import (
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    RawAuditRepositoryProtocol,
    SectorMembershipRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)

from .batch_identity import require_single_asset_identity
from .publication_sync import (
    PublishSectorMembershipBatchUseCase,
    PublishValuationBatchUseCase,
)
from .sync_use_cases import (
    RECOVERABLE_DATA_CENTER_EXCEPTIONS,
    _BaseSyncUseCase,
    _sync_status,
)


class SyncValuationUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: ValuationFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishValuationBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncValuationRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {
            "asset_code": request.asset_code,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        }
        try:
            facts = provider.fetch_valuations(request.asset_code, request.start, request.end)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            require_single_asset_identity(
                requested_asset_code=request.asset_code,
                returned_asset_codes=[fact.asset_code for fact in facts],
                label="valuation",
            )
            stored_count = self._facts.bulk_upsert(facts)
            if self._publication_publisher is not None and facts:
                self._publication_publisher.execute(
                    facts,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="valuation",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult("valuation", provider.provider_name(), stored_count, result_status)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="valuation",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


class SyncSectorMembershipUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: SectorMembershipRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishSectorMembershipBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncSectorMembershipRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {
            "sector_code": request.sector_code,
            "sector_name": request.sector_name,
            "effective_date": (
                request.effective_date.isoformat() if request.effective_date else None
            ),
        }
        try:
            facts = provider.fetch_sector_memberships(
                sector_code=request.sector_code,
                sector_name=request.sector_name,
                effective_date=request.effective_date,
            )
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(facts)
            if self._publication_publisher is not None and facts:
                self._publication_publisher.execute(
                    facts,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="sector_membership",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult(
                "sector_membership", provider.provider_name(), stored_count, result_status
            )
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="sector_membership",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


__all__ = ["SyncSectorMembershipUseCase", "SyncValuationUseCase"]
