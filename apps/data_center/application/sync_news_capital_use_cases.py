"""News and capital-flow provider synchronisation use cases."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.data_center.application.dtos import (
    SyncCapitalFlowRequest,
    SyncNewsRequest,
    SyncResult,
)
from apps.data_center.domain.protocols import (
    CapitalFlowRepositoryProtocol,
    NewsRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    RawAuditRepositoryProtocol,
)

from .publication_sync import PublishCapitalFlowBatchUseCase, PublishNewsBatchUseCase
from .sync_use_cases import (
    RECOVERABLE_DATA_CENTER_EXCEPTIONS,
    _BaseSyncUseCase,
    _sync_status,
)


class SyncNewsUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: NewsRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishNewsBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncNewsRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {"asset_code": request.asset_code, "limit": request.limit}
        try:
            facts = provider.fetch_news(request.asset_code, limit=request.limit)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_insert(facts)
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
                capability="news",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult("news", provider.provider_name(), stored_count, result_status)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="news",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


class SyncCapitalFlowUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: CapitalFlowRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishCapitalFlowBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncCapitalFlowRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {"asset_code": request.asset_code, "period": request.period}
        try:
            facts = provider.fetch_capital_flows(request.asset_code, period=request.period)
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
                capability="capital_flow",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult("capital_flow", provider.provider_name(), stored_count, result_status)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="capital_flow",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


__all__ = ["SyncCapitalFlowUseCase", "SyncNewsUseCase"]
