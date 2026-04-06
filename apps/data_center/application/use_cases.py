"""
Data Center — Application Layer Use Cases

Phase 1: Provider configuration management, connection testing, health status.
Phase 2: Asset resolution, macro series query, price history, latest quote.

No ORM or external-library imports — all I/O goes through injected protocols.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from datetime import date
from typing import TYPE_CHECKING

from apps.data_center.application.dtos import (
    AssetResponse,
    CreateProviderRequest,
    LatestQuoteRequest,
    MacroDataPoint,
    MacroSeriesRequest,
    MacroSeriesResponse,
    PriceBarResponse,
    PriceHistoryRequest,
    ProviderResponse,
    QuoteResponse,
    ResolveAssetRequest,
    SyncCapitalFlowRequest,
    SyncFinancialRequest,
    SyncFundNavRequest,
    SyncMacroRequest,
    SyncNewsRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncResult,
    SyncSectorMembershipRequest,
    SyncValuationRequest,
    UpdateProviderRequest,
)
from apps.data_center.domain.entities import ConnectionTestResult, ProviderConfig, RawAudit
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.protocols import (
    AssetRepositoryProtocol,
    CapitalFlowRepositoryProtocol,
    ConnectionTesterProtocol,
    FinancialFactRepositoryProtocol,
    FundNavRepositoryProtocol,
    IndicatorCatalogRepositoryProtocol,
    LegacyMacroSeriesRepositoryProtocol,
    MacroFactRepositoryProtocol,
    NewsRepositoryProtocol,
    PriceBarRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    QuoteSnapshotRepositoryProtocol,
    RawAuditRepositoryProtocol,
    RegistryProtocol,
    SectorMembershipRepositoryProtocol,
    UnifiedDataProviderProtocol,
    ValuationFactRepositoryProtocol,
)
from apps.data_center.domain.rules import normalize_asset_code

if TYPE_CHECKING:
    from apps.data_center.domain.entities import ProviderHealthSnapshot

logger = logging.getLogger(__name__)


def _config_to_response(config: ProviderConfig) -> ProviderResponse:
    return ProviderResponse(
        id=config.id,
        name=config.name,
        source_type=config.source_type,
        is_active=config.is_active,
        priority=config.priority,
        api_key=config.api_key,
        api_secret=config.api_secret,
        http_url=config.http_url,
        api_endpoint=config.api_endpoint,
        extra_config=config.extra_config,
        description=config.description,
    )


class ManageProviderConfigUseCase:
    """CRUD operations for provider configurations.

    Args:
        repo: Injected ProviderConfigRepositoryProtocol implementation.
    """

    def __init__(self, repo: ProviderConfigRepositoryProtocol) -> None:
        self._repo = repo

    def list_all(self) -> list[ProviderResponse]:
        return [_config_to_response(c) for c in self._repo.list_all()]

    def get(self, provider_id: int) -> ProviderResponse | None:
        config = self._repo.get_by_id(provider_id)
        return _config_to_response(config) if config else None

    def create(self, request: CreateProviderRequest) -> ProviderResponse:
        config = ProviderConfig(
            id=None,
            name=request.name,
            source_type=request.source_type,
            is_active=request.is_active,
            priority=request.priority,
            api_key=request.api_key,
            api_secret=request.api_secret,
            http_url=request.http_url,
            api_endpoint=request.api_endpoint,
            extra_config=request.extra_config,
            description=request.description,
        )
        saved = self._repo.save(config)
        logger.info("Created provider config: %s", saved.name)
        return _config_to_response(saved)

    def update(self, request: UpdateProviderRequest) -> ProviderResponse | None:
        existing = self._repo.get_by_id(request.provider_id)
        if existing is None:
            return None

        # Apply only the fields that were explicitly provided (non-None)
        updated = ProviderConfig(
            id=existing.id,
            name=request.name if request.name is not None else existing.name,
            source_type=(
                request.source_type
                if request.source_type is not None
                else existing.source_type
            ),
            is_active=(
                request.is_active
                if request.is_active is not None
                else existing.is_active
            ),
            priority=(
                request.priority if request.priority is not None else existing.priority
            ),
            api_key=(
                request.api_key if request.api_key is not None else existing.api_key
            ),
            api_secret=(
                request.api_secret
                if request.api_secret is not None
                else existing.api_secret
            ),
            http_url=(
                request.http_url if request.http_url is not None else existing.http_url
            ),
            api_endpoint=(
                request.api_endpoint
                if request.api_endpoint is not None
                else existing.api_endpoint
            ),
            extra_config=(
                request.extra_config
                if request.extra_config is not None
                else existing.extra_config
            ),
            description=(
                request.description
                if request.description is not None
                else existing.description
            ),
        )
        saved = self._repo.save(updated)
        logger.info("Updated provider config id=%s name=%s", saved.id, saved.name)
        return _config_to_response(saved)

    def delete(self, provider_id: int) -> bool:
        if self._repo.get_by_id(provider_id) is None:
            return False
        self._repo.delete(provider_id)
        logger.info("Deleted provider config id=%s", provider_id)
        return True


class RunProviderConnectionTestUseCase:
    """Run a connectivity probe against a configured provider.

    Args:
        repo: Used to look up provider config by id.
        tester: Injected ConnectionTesterProtocol implementation.
    """

    def __init__(
        self,
        repo: ProviderConfigRepositoryProtocol,
        tester: ConnectionTesterProtocol,
    ) -> None:
        self._repo = repo
        self._tester = tester

    def execute(self, provider_id: int) -> ConnectionTestResult | None:
        """Return a ConnectionTestResult, or None if the provider was not found."""
        config = self._repo.get_by_id(provider_id)
        if config is None:
            return None
        logger.info("Running connection test for provider id=%s (%s)", provider_id, config.name)
        return self._tester.test(config)


class GetProviderStatusUseCase:
    """Query live health snapshots from the runtime registry.

    Args:
        registry: Injected RegistryProtocol implementation.
    """

    def __init__(self, registry: RegistryProtocol) -> None:
        self._registry = registry

    def execute(self) -> list[ProviderHealthSnapshot]:
        return self._registry.get_all_statuses()


# ---------------------------------------------------------------------------
# Phase 2 — Query use cases
# ---------------------------------------------------------------------------


class ResolveAssetUseCase:
    """Resolve a potentially provider-specific ticker to canonical AssetMaster.

    Normalises the input code via domain rules before hitting the repository,
    so callers can pass AKShare / Wind / Baostock codes directly.
    """

    def __init__(self, repo: AssetRepositoryProtocol) -> None:
        self._repo = repo

    def execute(self, request: ResolveAssetRequest) -> AssetResponse | None:
        canonical = normalize_asset_code(request.code, request.source_type)
        asset = self._repo.get_by_code(canonical)
        if asset is None and canonical != request.code:
            # Try the raw code as fallback
            asset = self._repo.get_by_code(request.code)
        if asset is None:
            return None
        return AssetResponse(
            code=asset.code,
            name=asset.name,
            short_name=asset.short_name,
            asset_type=asset.asset_type.value,
            exchange=asset.exchange.value,
            is_active=asset.is_active,
            list_date=asset.list_date,
            sector=asset.sector,
            industry=asset.industry,
            currency=asset.currency,
        )


class QueryMacroSeriesUseCase:
    """Fetch a macro economic time-series by indicator code.

    Enriches the response with indicator metadata from IndicatorCatalog.
    """

    def __init__(
        self,
        fact_repo: MacroFactRepositoryProtocol,
        catalog_repo: IndicatorCatalogRepositoryProtocol,
        legacy_repo: LegacyMacroSeriesRepositoryProtocol | None = None,
    ) -> None:
        self._facts = fact_repo
        self._catalog = catalog_repo
        self._legacy = legacy_repo

    def execute(self, request: MacroSeriesRequest) -> MacroSeriesResponse:
        facts = self._facts.get_series(
            indicator_code=request.indicator_code,
            start=request.start,
            end=request.end,
            limit=request.limit,
        )
        if request.source:
            facts = [f for f in facts if f.source == request.source]

        catalog = self._catalog.get_by_code(request.indicator_code)
        name_cn = catalog.name_cn if catalog else request.indicator_code

        data_points: list[MacroDataPoint]
        if facts:
            data_points = [
                MacroDataPoint(
                    indicator_code=f.indicator_code,
                    reporting_period=f.reporting_period,
                    value=f.value,
                    unit=f.unit,
                    source=f.source,
                    quality=f.quality.value,
                    published_at=f.published_at,
                )
                for f in facts
            ]
        elif self._legacy is not None:
            legacy_facts = self._legacy.get_series(
                code=request.indicator_code,
                start_date=request.start,
                end_date=request.end,
                source=request.source,
            )
            data_points = [
                MacroDataPoint(
                    indicator_code=getattr(f, "code"),
                    reporting_period=getattr(f, "reporting_period"),
                    value=float(getattr(f, "value")),
                    unit=getattr(f, "unit"),
                    source=getattr(f, "source"),
                    quality="legacy",
                    published_at=getattr(f, "published_at"),
                )
                for f in legacy_facts[: request.limit]
            ]
        else:
            data_points = []

        return MacroSeriesResponse(
            indicator_code=request.indicator_code,
            name_cn=name_cn,
            data=data_points,
            total=len(data_points),
        )


class QueryPriceHistoryUseCase:
    """Fetch OHLCV price bars for a security."""

    def __init__(self, repo: PriceBarRepositoryProtocol) -> None:
        self._repo = repo

    def execute(self, request: PriceHistoryRequest) -> list[PriceBarResponse]:
        bars = self._repo.get_bars(
            asset_code=request.asset_code,
            start=request.start,
            end=request.end,
            limit=request.limit,
        )
        return [
            PriceBarResponse(
                asset_code=b.asset_code,
                bar_date=b.bar_date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                amount=b.amount,
                source=b.source,
            )
            for b in bars
        ]


class QueryLatestQuoteUseCase:
    """Fetch the most recent real-time quote snapshot for a security."""

    def __init__(self, repo: QuoteSnapshotRepositoryProtocol) -> None:
        self._repo = repo

    def execute(self, request: LatestQuoteRequest) -> QuoteResponse | None:
        quote = self._repo.get_latest(request.asset_code)
        if quote is None:
            return None
        return QuoteResponse(
            asset_code=quote.asset_code,
            snapshot_at=quote.snapshot_at,
            current_price=quote.current_price,
            open=quote.open,
            high=quote.high,
            low=quote.low,
            prev_close=quote.prev_close,
            volume=quote.volume,
            source=quote.source,
        )


class QueryFundNavUseCase:
    """Fetch fund NAV history."""

    def __init__(self, repo: FundNavRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        fund_code: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[dict[str, object]]:
        return [fact.to_dict() for fact in self._repo.get_series(fund_code, start, end)]


class QueryFinancialsUseCase:
    """Fetch financial facts for one asset."""

    def __init__(self, repo: FinancialFactRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        asset_code: str,
        period_type: FinancialPeriodType | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        return [
            fact.to_dict()
            for fact in self._repo.get_facts(asset_code, period_type=period_type, limit=limit)
        ]


class QueryValuationsUseCase:
    """Fetch valuation history for one asset."""

    def __init__(self, repo: ValuationFactRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[dict[str, object]]:
        return [fact.to_dict() for fact in self._repo.get_series(asset_code, start, end)]


class QuerySectorConstituentsUseCase:
    """Fetch members for one sector."""

    def __init__(self, repo: SectorMembershipRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        sector_code: str,
        as_of: date | None = None,
    ) -> list[dict[str, object]]:
        return [fact.to_dict() for fact in self._repo.get_members(sector_code, as_of)]


class QueryNewsUseCase:
    """Fetch news articles."""

    def __init__(self, repo: NewsRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        asset_code: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        return [fact.to_dict() for fact in self._repo.get_recent(asset_code, limit)]


class QueryCapitalFlowsUseCase:
    """Fetch capital flow history for one asset."""

    def __init__(self, repo: CapitalFlowRepositoryProtocol) -> None:
        self._repo = repo

    def execute(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[dict[str, object]]:
        return [fact.to_dict() for fact in self._repo.get_series(asset_code, start, end)]


# ---------------------------------------------------------------------------
# Phase 3 — Sync use cases
# ---------------------------------------------------------------------------


def _build_sync_audit(
    provider_name: str,
    capability: str,
    request_params: dict[str, object],
    status: str,
    row_count: int,
    latency_ms: float,
    error_message: str = "",
) -> RawAudit:
    return RawAudit(
        provider_name=provider_name,
        capability=capability,
        request_params=request_params,
        status=status,
        row_count=row_count,
        latency_ms=latency_ms,
        error_message=error_message,
        fetched_at=datetime.now(timezone.utc),
    )


class _BaseSyncUseCase:
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_factory = provider_factory
        self._raw_audit_repo = raw_audit_repo

    def _get_provider(self, provider_id: int) -> tuple[ProviderConfig, UnifiedDataProviderProtocol]:
        config = self._provider_repo.get_by_id(provider_id)
        if config is None:
            raise ValueError(f"Provider not found: {provider_id}")
        provider = self._provider_factory.get_by_id(provider_id)
        if provider is None:
            raise ValueError(f"Provider adapter unavailable: {provider_id}")
        return config, provider


class SyncMacroUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        fact_repo: MacroFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_factory, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncMacroRequest) -> SyncResult:
        _config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            facts = provider.fetch_macro_series(request.indicator_code, request.start, request.end)
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "macro",
                    {
                        "indicator_code": request.indicator_code,
                        "start": request.start.isoformat(),
                        "end": request.end.isoformat(),
                    },
                    "ok",
                    stored_count,
                    latency_ms,
                )
            )
            return SyncResult("macro", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "macro",
                    {
                        "indicator_code": request.indicator_code,
                        "start": request.start.isoformat(),
                        "end": request.end.isoformat(),
                    },
                    "error",
                    0,
                    latency_ms,
                    str(exc),
                )
            )
            raise


class SyncPriceUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        fact_repo: PriceBarRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_factory, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncPriceRequest) -> SyncResult:
        _config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            bars = provider.fetch_price_history(request.asset_code, request.start, request.end)
            stored_count = self._facts.bulk_upsert(bars)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "historical_price",
                    {
                        "asset_code": request.asset_code,
                        "start": request.start.isoformat(),
                        "end": request.end.isoformat(),
                    },
                    "ok",
                    stored_count,
                    latency_ms,
                )
            )
            return SyncResult("historical_price", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "historical_price",
                    {"asset_code": request.asset_code, "start": request.start.isoformat(), "end": request.end.isoformat()},
                    "error", 0, latency_ms, str(exc),
                )
            )
            raise


class SyncQuoteUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        fact_repo: QuoteSnapshotRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_factory, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncQuoteRequest) -> SyncResult:
        _config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            quotes = provider.fetch_quote_snapshots(request.asset_codes)
            stored_count = self._facts.bulk_upsert(quotes)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "realtime_quote",
                    {"asset_codes": request.asset_codes},
                    "ok",
                    stored_count,
                    latency_ms,
                )
            )
            return SyncResult("realtime_quote", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(), "realtime_quote",
                    {"asset_codes": request.asset_codes}, "error", 0, latency_ms, str(exc),
                )
            )
            raise


class SyncFundNavUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        fact_repo: FundNavRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_factory, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncFundNavRequest) -> SyncResult:
        _config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            facts = provider.fetch_fund_nav(request.fund_code, request.start, request.end)
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "fund_nav",
                    {
                        "fund_code": request.fund_code,
                        "start": request.start.isoformat(),
                        "end": request.end.isoformat(),
                    },
                    "ok",
                    stored_count,
                    latency_ms,
                )
            )
            return SyncResult("fund_nav", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(), "fund_nav",
                    {"fund_code": request.fund_code, "start": request.start.isoformat(), "end": request.end.isoformat()},
                    "error", 0, latency_ms, str(exc),
                )
            )
            raise


class SyncFinancialUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        fact_repo: FinancialFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_factory, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncFinancialRequest) -> SyncResult:
        _config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            facts = provider.fetch_financials(request.asset_code, periods=request.periods)
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "financial",
                    {"asset_code": request.asset_code, "periods": request.periods},
                    "ok",
                    stored_count,
                    latency_ms,
                )
            )
            return SyncResult("financial", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(), "financial",
                    {"asset_code": request.asset_code, "periods": request.periods},
                    "error", 0, latency_ms, str(exc),
                )
            )
            raise


class SyncValuationUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        fact_repo: ValuationFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_factory, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncValuationRequest) -> SyncResult:
        _config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            facts = provider.fetch_valuations(request.asset_code, request.start, request.end)
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "valuation",
                    {
                        "asset_code": request.asset_code,
                        "start": request.start.isoformat(),
                        "end": request.end.isoformat(),
                    },
                    "ok",
                    stored_count,
                    latency_ms,
                )
            )
            return SyncResult("valuation", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(), "valuation",
                    {"asset_code": request.asset_code, "start": request.start.isoformat(), "end": request.end.isoformat()},
                    "error", 0, latency_ms, str(exc),
                )
            )
            raise


class SyncSectorMembershipUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        fact_repo: SectorMembershipRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_factory, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncSectorMembershipRequest) -> SyncResult:
        _config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        params = {
            "sector_code": request.sector_code,
            "sector_name": request.sector_name,
            "effective_date": request.effective_date.isoformat() if request.effective_date else None,
        }
        try:
            facts = provider.fetch_sector_memberships(
                sector_code=request.sector_code,
                sector_name=request.sector_name,
                effective_date=request.effective_date,
            )
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(provider.provider_name(), "sector_membership", params, "ok", stored_count, latency_ms)
            )
            return SyncResult("sector_membership", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(provider.provider_name(), "sector_membership", params, "error", 0, latency_ms, str(exc))
            )
            raise


class SyncNewsUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        fact_repo: NewsRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_factory, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncNewsRequest) -> SyncResult:
        _config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        params = {"asset_code": request.asset_code, "limit": request.limit}
        try:
            facts = provider.fetch_news(request.asset_code, limit=request.limit)
            stored_count = self._facts.bulk_insert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(provider.provider_name(), "news", params, "ok", stored_count, latency_ms)
            )
            return SyncResult("news", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(provider.provider_name(), "news", params, "error", 0, latency_ms, str(exc))
            )
            raise


class SyncCapitalFlowUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        fact_repo: CapitalFlowRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_factory, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncCapitalFlowRequest) -> SyncResult:
        _config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        params = {"asset_code": request.asset_code, "period": request.period}
        try:
            facts = provider.fetch_capital_flows(request.asset_code, period=request.period)
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(provider.provider_name(), "capital_flow", params, "ok", stored_count, latency_ms)
            )
            return SyncResult("capital_flow", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(provider.provider_name(), "capital_flow", params, "error", 0, latency_ms, str(exc))
            )
            raise
