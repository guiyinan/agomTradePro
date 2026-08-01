"""Current valuation batch synchronization."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

from apps.data_center.application.dtos import SyncValuationBatchResult
from apps.data_center.domain.protocols import (
    CurrentValuationBatchProviderProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    RawAuditRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)

from .sync_use_cases import RECOVERABLE_DATA_CENTER_EXCEPTIONS, _BaseSyncUseCase


class SyncCurrentValuationBatchUseCase(_BaseSyncUseCase):
    """Persist current valuation coverage with an optional provider batch capability."""

    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: ValuationFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo

    def execute(
        self,
        *,
        provider_id: int,
        asset_codes: list[str],
        as_of_date: date,
    ) -> SyncValuationBatchResult:
        """Fetch and store one current valuation row per available asset."""

        config, provider = self._get_provider(provider_id)
        started = datetime.now(UTC)
        params = {"asset_count": len(asset_codes), "as_of_date": as_of_date.isoformat()}
        try:
            if isinstance(provider, CurrentValuationBatchProviderProtocol):
                facts = provider.fetch_current_valuations(asset_codes, as_of_date)
            else:
                facts = []
                for asset_code in asset_codes:
                    facts.extend(provider.fetch_valuations(asset_code, as_of_date, as_of_date))
            facts = [
                dataclasses.replace(fact, source=str(fact.source or config.source_type).strip())
                for fact in facts
            ]
            stored_count = self._facts.bulk_upsert(facts)
            succeeded_asset_codes = sorted({fact.asset_code for fact in facts})
            complete = len(succeeded_asset_codes) == len(asset_codes)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="valuation",
                request_params=params,
                status="ok" if complete else "partial",
                row_count=stored_count,
                latency_ms=latency_ms,
                error_message="" if complete else "valuation_batch_incomplete",
            )
            return SyncValuationBatchResult(
                domain="valuation",
                provider_name=provider.provider_name(),
                stored_count=stored_count,
                status="success" if complete else "partial",
                succeeded_asset_codes=succeeded_asset_codes,
            )
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
