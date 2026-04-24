"""
Data Center — Application Layer Use Cases

Phase 1: Provider configuration management, connection testing, health status.
Phase 2: Asset resolution, macro series query, price history, latest quote.

No ORM or external-library imports — all I/O goes through injected protocols.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from apps.data_center.application.dtos import (
    AssetResponse,
    CreateProviderRequest,
    DecisionReliabilityRepairReport,
    DecisionReliabilityRepairRequest,
    DecisionReliabilitySection,
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
from apps.data_center.domain.enums import DataCapability, FinancialPeriodType
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
from apps.data_center.domain.rules import (
    get_macro_age_days,
    is_macro_observation_stale,
    is_stale,
    normalize_asset_code,
)

if TYPE_CHECKING:
    from apps.data_center.domain.entities import ProviderHealthSnapshot

logger = logging.getLogger(__name__)
DEFAULT_LATEST_QUOTE_MAX_AGE_HOURS = 4.0
DEFAULT_DECISION_MACRO_INDICATORS = (
    "CN_PMI",
    "CN_NEW_CREDIT",
    "CN_CPI_NATIONAL_YOY",
    "CN_SHIBOR",
    "CN_LPR",
    "CN_M2",
)
DEFAULT_DECISION_ASSET_CODES = ("510300.SH", "000300.SH")
AKSHARE_MACRO_INDICATORS = frozenset(DEFAULT_DECISION_MACRO_INDICATORS)
_SOURCE_TYPE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "tushare": (
        DataCapability.MACRO.value,
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.REALTIME_QUOTE.value,
        DataCapability.FUND_NAV.value,
        DataCapability.FINANCIAL.value,
        DataCapability.VALUATION.value,
    ),
    "akshare": (
        DataCapability.MACRO.value,
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.REALTIME_QUOTE.value,
        DataCapability.FUND_NAV.value,
        DataCapability.FINANCIAL.value,
        DataCapability.VALUATION.value,
        DataCapability.SECTOR_MEMBERSHIP.value,
        DataCapability.NEWS.value,
        DataCapability.CAPITAL_FLOW.value,
    ),
    "eastmoney": (
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.REALTIME_QUOTE.value,
        DataCapability.NEWS.value,
        DataCapability.CAPITAL_FLOW.value,
    ),
    "qmt": (
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.REALTIME_QUOTE.value,
    ),
    "fred": (DataCapability.MACRO.value,),
    "wind": (
        DataCapability.MACRO.value,
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.FINANCIAL.value,
        DataCapability.VALUATION.value,
        DataCapability.SECTOR_MEMBERSHIP.value,
    ),
    "choice": (
        DataCapability.MACRO.value,
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.FINANCIAL.value,
    ),
}


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
                request.source_type if request.source_type is not None else existing.source_type
            ),
            is_active=(request.is_active if request.is_active is not None else existing.is_active),
            priority=(request.priority if request.priority is not None else existing.priority),
            api_key=(request.api_key if request.api_key is not None else existing.api_key),
            api_secret=(
                request.api_secret if request.api_secret is not None else existing.api_secret
            ),
            http_url=(request.http_url if request.http_url is not None else existing.http_url),
            api_endpoint=(
                request.api_endpoint if request.api_endpoint is not None else existing.api_endpoint
            ),
            extra_config=(
                request.extra_config if request.extra_config is not None else existing.extra_config
            ),
            description=(
                request.description if request.description is not None else existing.description
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
        result = self._tester.test(config)
        self._persist_provider_health_probe(config, result)
        return result

    def _persist_provider_health_probe(
        self,
        config: ProviderConfig,
        result: ConnectionTestResult,
    ) -> None:
        extra_config = dict(config.extra_config or {})
        recorded_at = result.tested_at

        extra_config["provider_last_success_at"] = (
            recorded_at.isoformat()
            if result.success
            else extra_config.get("provider_last_success_at")
        )
        extra_config["provider_last_probe_at"] = recorded_at.isoformat()
        extra_config["provider_last_status"] = "healthy" if result.success else "degraded"
        extra_config["provider_last_error"] = "" if result.success else result.summary

        capability_metrics = dict(extra_config.get("health_metrics") or {})
        for capability in _SOURCE_TYPE_CAPABILITIES.get(config.source_type, ()):
            metric = dict(capability_metrics.get(capability) or {})
            if result.success:
                metric["last_success_at"] = recorded_at.isoformat()
                metric["consecutive_failures"] = 0
                metric["last_status"] = "healthy"
                metric["last_error"] = ""
            else:
                metric["consecutive_failures"] = int(metric.get("consecutive_failures", 0)) + 1
                metric["last_failure_at"] = recorded_at.isoformat()
                metric["last_status"] = "degraded"
                metric["last_error"] = result.summary
            capability_metrics[capability] = metric

        extra_config["health_metrics"] = capability_metrics
        self._repo.save(dataclasses.replace(config, extra_config=extra_config))


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
        period_type = catalog.default_period_type if catalog else "M"

        data_points: list[MacroDataPoint]
        legacy_available = False
        legacy_used = False
        data_source = "none"
        freshness_status = "missing"
        decision_grade = "blocked"
        must_not_use_for_decision = True
        blocked_reason = "当前无可用宏观数据。"
        if facts:
            data_source = "data_center_fact"
            data_points = [
                self._build_macro_data_point(
                    indicator_code=f.indicator_code,
                    reporting_period=f.reporting_period,
                    value=f.value,
                    unit=f.unit,
                    source=f.source,
                    quality=f.quality.value,
                    published_at=f.published_at,
                    period_type=period_type,
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
            legacy_available = len(legacy_facts) > 0
            if request.allow_legacy_fallback:
                legacy_used = legacy_available
                data_source = "legacy"
                data_points = [
                    self._build_macro_data_point(
                        indicator_code=getattr(f, "code"),
                        reporting_period=getattr(f, "reporting_period"),
                        value=float(getattr(f, "value")),
                        unit=getattr(f, "unit"),
                        source=getattr(f, "source"),
                        quality="legacy",
                        published_at=getattr(f, "published_at"),
                        period_type=period_type,
                    )
                    for f in legacy_facts[: request.limit]
                ]
                if legacy_used:
                    freshness_status = "legacy_fallback"
                    decision_grade = "degraded"
                    blocked_reason = (
                        "当前标准事实表无数据；已按显式请求回退到 legacy 宏观数据。"
                        "该结果仅可用于研究，不可直接用于决策。"
                    )
            else:
                data_points = []
                if legacy_available:
                    freshness_status = "legacy_blocked"
                    blocked_reason = (
                        "标准事实表当前无数据，且默认决策安全口径已阻断 legacy fallback。"
                        "如需研究旧链路数据，请显式传入 allow_legacy_fallback=true。"
                    )
                else:
                    blocked_reason = "当前无可用宏观数据。"
        else:
            data_points = []

        if data_points and not legacy_used:
            latest = data_points[0]
            if latest.is_stale:
                freshness_status = "stale"
                decision_grade = "degraded"
                blocked_reason = (
                    "最新宏观数据已超过 freshness 阈值，当前结果仅可用于研究，不可直接用于决策。"
                )
            else:
                freshness_status = "fresh"
                decision_grade = "decision_safe"
                must_not_use_for_decision = False
                blocked_reason = ""
        elif data_points and legacy_used:
            must_not_use_for_decision = True

        latest_reporting_period = data_points[0].reporting_period if data_points else None
        latest_published_at = data_points[0].published_at if data_points else None
        latest_quality = data_points[0].quality if data_points else ""

        return MacroSeriesResponse(
            indicator_code=request.indicator_code,
            name_cn=name_cn,
            period_type=period_type,
            data=data_points,
            total=len(data_points),
            data_source=data_source,
            freshness_status=freshness_status,
            decision_grade=decision_grade,
            must_not_use_for_decision=must_not_use_for_decision,
            blocked_reason=blocked_reason,
            latest_reporting_period=latest_reporting_period,
            latest_published_at=latest_published_at,
            latest_quality=latest_quality,
            legacy_fallback_available=legacy_available,
            legacy_fallback_used=legacy_used,
        )

    def _build_macro_data_point(
        self,
        *,
        indicator_code: str,
        reporting_period: date,
        value: float,
        unit: str,
        source: str,
        quality: str,
        published_at: date | None,
        period_type: str,
    ) -> MacroDataPoint:
        age_days = get_macro_age_days(reporting_period, published_at)
        point_is_stale = is_macro_observation_stale(
            reporting_period,
            published_at,
            period_type=period_type,
        )
        decision_grade = "decision_safe"
        if quality == "legacy":
            decision_grade = "degraded"
        elif point_is_stale:
            decision_grade = "degraded"

        return MacroDataPoint(
            indicator_code=indicator_code,
            reporting_period=reporting_period,
            value=value,
            unit=unit,
            source=source,
            quality=quality,
            published_at=published_at,
            age_days=age_days,
            is_stale=point_is_stale,
            freshness_status="stale" if point_is_stale else "fresh",
            decision_grade=decision_grade,
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

    DEFAULT_MAX_AGE_HOURS = DEFAULT_LATEST_QUOTE_MAX_AGE_HOURS

    def __init__(self, repo: QuoteSnapshotRepositoryProtocol) -> None:
        self._repo = repo

    @classmethod
    def build_response(
        cls,
        *,
        asset_code: str,
        snapshot_at: datetime,
        current_price: float,
        open: float | None,
        high: float | None,
        low: float | None,
        prev_close: float | None,
        volume: float | None,
        source: str,
        max_age_hours: float | None = None,
    ) -> QuoteResponse:
        effective_max_age_hours = (
            cls.DEFAULT_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
        )
        if effective_max_age_hours <= 0:
            raise ValueError("max_age_hours must be greater than 0")

        normalized_snapshot_at = snapshot_at
        if normalized_snapshot_at.tzinfo is None:
            normalized_snapshot_at = normalized_snapshot_at.replace(tzinfo=timezone.utc)
        else:
            normalized_snapshot_at = normalized_snapshot_at.astimezone(timezone.utc)

        age_seconds = max(
            0.0,
            (datetime.now(timezone.utc) - normalized_snapshot_at).total_seconds(),
        )
        age_minutes = int(age_seconds // 60)
        quote_is_stale = is_stale(normalized_snapshot_at, effective_max_age_hours)
        blocked_reason = ""
        if quote_is_stale:
            blocked_reason = (
                "最新行情快照已超过 freshness 阈值，当前结果仅可用于诊断，" "不得直接用于决策。"
            )

        return QuoteResponse(
            asset_code=asset_code,
            snapshot_at=normalized_snapshot_at,
            current_price=current_price,
            open=open,
            high=high,
            low=low,
            prev_close=prev_close,
            volume=volume,
            source=source,
            age_minutes=age_minutes,
            is_stale=quote_is_stale,
            freshness_status="stale" if quote_is_stale else "fresh",
            must_not_use_for_decision=quote_is_stale,
            blocked_reason=blocked_reason,
            max_age_hours=effective_max_age_hours,
        )

    def execute(self, request: LatestQuoteRequest) -> QuoteResponse | None:
        quote = self._repo.get_latest(request.asset_code)
        if quote is None:
            return None
        return self.build_response(
            asset_code=quote.asset_code,
            snapshot_at=quote.snapshot_at,
            current_price=quote.current_price,
            open=quote.open,
            high=quote.high,
            low=quote.low,
            prev_close=quote.prev_close,
            volume=quote.volume,
            source=quote.source,
            max_age_hours=request.max_age_hours,
        )


class RepairDecisionDataReliabilityUseCase:
    """Repair and re-check the data chain required for actionable decisions."""

    def __init__(
        self,
        *,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_factory,
        macro_fact_repo: MacroFactRepositoryProtocol,
        indicator_catalog_repo: IndicatorCatalogRepositoryProtocol,
        price_bar_repo: PriceBarRepositoryProtocol,
        quote_snapshot_repo: QuoteSnapshotRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        legacy_macro_repo: LegacyMacroSeriesRepositoryProtocol | None = None,
        pulse_refresher: Callable[[date], Any] | None = None,
        alpha_refresher: Callable[[date, int | None], dict[str, Any]] | None = None,
        alpha_status_reader: Callable[[date, int | None], dict[str, Any]] | None = None,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_factory = provider_factory
        self._macro_fact_repo = macro_fact_repo
        self._indicator_catalog_repo = indicator_catalog_repo
        self._price_bar_repo = price_bar_repo
        self._quote_snapshot_repo = quote_snapshot_repo
        self._raw_audit_repo = raw_audit_repo
        self._legacy_macro_repo = legacy_macro_repo
        self._pulse_refresher = pulse_refresher
        self._alpha_refresher = alpha_refresher
        self._alpha_status_reader = alpha_status_reader

    def execute(
        self,
        request: DecisionReliabilityRepairRequest,
    ) -> DecisionReliabilityRepairReport:
        target_date = request.target_date or date.today()
        asset_codes = self._normalize_unique(
            request.asset_codes or list(DEFAULT_DECISION_ASSET_CODES)
        )
        macro_codes = self._normalize_unique(
            request.macro_indicator_codes or list(DEFAULT_DECISION_MACRO_INDICATORS)
        )

        provider_bootstrap = self._ensure_default_akshare_provider()
        macro_status = self._repair_macro_inputs(request, target_date, macro_codes)
        quote_status = self._repair_quote_inputs(request, target_date, asset_codes)
        pulse_status = self._repair_pulse(request, target_date)
        alpha_status = self._repair_alpha(request, target_date)

        return DecisionReliabilityRepairReport(
            target_date=target_date,
            portfolio_id=request.portfolio_id,
            macro_status=macro_status,
            quote_status=quote_status,
            pulse_status=pulse_status,
            alpha_status=alpha_status,
            provider_bootstrap=provider_bootstrap,
        )

    def _ensure_default_akshare_provider(self) -> dict[str, Any]:
        existing = [
            provider
            for provider in self._provider_repo.list_all()
            if provider.source_type == "akshare"
        ]
        active = [provider for provider in existing if provider.is_active]
        if active:
            return {
                "status": "exists",
                "provider_id": active[0].id,
                "provider_name": active[0].name,
            }
        if existing:
            return {
                "status": "inactive_exists",
                "provider_id": existing[0].id,
                "provider_name": existing[0].name,
                "message": "已存在非启用 AKShare provider，未覆盖用户配置。",
            }

        saved = self._provider_repo.save(
            ProviderConfig(
                id=None,
                name="AKShare Public",
                source_type="akshare",
                is_active=True,
                priority=10,
                api_key="",
                api_secret="",
                http_url="",
                api_endpoint="",
                extra_config={"managed_by": "decision_reliability_repair"},
                description="Default public AKShare provider for decision data repair.",
            )
        )
        return {
            "status": "created",
            "provider_id": saved.id,
            "provider_name": saved.name,
        }

    def _repair_macro_inputs(
        self,
        request: DecisionReliabilityRepairRequest,
        target_date: date,
        macro_codes: list[str],
    ) -> DecisionReliabilitySection:
        start_date = target_date - timedelta(days=max(request.macro_lookback_days, 30))
        details: dict[str, Any] = {"indicators": {}}
        blocked_reasons: list[str] = []
        failed = False

        for indicator_code in macro_codes:
            provider = self._select_macro_provider(indicator_code)
            indicator_details: dict[str, Any] = {}
            if provider is None or provider.id is None:
                reason = f"{indicator_code}: 无可用宏观 provider。"
                blocked_reasons.append(reason)
                details["indicators"][indicator_code] = {
                    "status": "blocked",
                    "blocked_reason": reason,
                }
                continue

            indicator_details["provider_id"] = provider.id
            indicator_details["provider_name"] = provider.name
            try:
                sync_result = SyncMacroUseCase(
                    provider_repo=self._provider_repo,
                    provider_factory=self._provider_factory,
                    fact_repo=self._macro_fact_repo,
                    raw_audit_repo=self._raw_audit_repo,
                ).execute(
                    SyncMacroRequest(
                        provider_id=provider.id,
                        indicator_code=indicator_code,
                        start=start_date,
                        end=target_date,
                    )
                )
                indicator_details["sync"] = sync_result.to_dict()
            except Exception as exc:
                failed = True
                blocked_reasons.append(f"{indicator_code}: 同步失败: {exc}")
                indicator_details["sync"] = {
                    "status": "failed",
                    "error_message": str(exc),
                }

            query = QueryMacroSeriesUseCase(
                self._macro_fact_repo,
                self._indicator_catalog_repo,
                self._legacy_macro_repo,
            ).execute(
                MacroSeriesRequest(
                    indicator_code=indicator_code,
                    end=target_date,
                    limit=1,
                    allow_legacy_fallback=False,
                )
            )
            query_dict = query.to_dict()
            indicator_details["freshness"] = query_dict["contract"]
            if query.must_not_use_for_decision:
                blocked_reasons.append(
                    f"{indicator_code}: {query.blocked_reason or query.freshness_status}"
                )
            details["indicators"][indicator_code] = indicator_details

        status_value = "ready"
        if failed:
            status_value = "failed"
        elif blocked_reasons:
            status_value = "blocked"

        return DecisionReliabilitySection(
            status=status_value,
            must_not_use_for_decision=failed or bool(blocked_reasons),
            blocked_reasons=blocked_reasons,
            details=details,
        )

    def _repair_quote_inputs(
        self,
        request: DecisionReliabilityRepairRequest,
        target_date: date,
        asset_codes: list[str],
    ) -> DecisionReliabilitySection:
        details: dict[str, Any] = {"quotes": {}, "prices": {}}
        blocked_reasons: list[str] = []
        failed = False

        quote_provider = self._select_provider_by_types(
            ("akshare", "eastmoney", "tushare"),
            DataCapability.REALTIME_QUOTE.value,
        )
        if quote_provider is None or quote_provider.id is None:
            blocked_reasons.append("无可用实时行情 provider。")
        else:
            try:
                sync_result = SyncQuoteUseCase(
                    provider_repo=self._provider_repo,
                    provider_factory=self._provider_factory,
                    fact_repo=self._quote_snapshot_repo,
                    raw_audit_repo=self._raw_audit_repo,
                ).execute(
                    SyncQuoteRequest(
                        provider_id=quote_provider.id,
                        asset_codes=asset_codes,
                    )
                )
                details["quote_sync"] = sync_result.to_dict()
            except Exception as exc:
                failed = True
                blocked_reasons.append(f"实时行情同步失败: {exc}")
                details["quote_sync"] = {
                    "status": "failed",
                    "error_message": str(exc),
                }

        price_provider = self._select_provider_by_types(
            ("akshare", "eastmoney", "tushare"),
            DataCapability.HISTORICAL_PRICE.value,
        )
        if price_provider is None or price_provider.id is None:
            blocked_reasons.append("无可用历史价格 provider。")
        else:
            for asset_code in asset_codes:
                try:
                    sync_result = SyncPriceUseCase(
                        provider_repo=self._provider_repo,
                        provider_factory=self._provider_factory,
                        fact_repo=self._price_bar_repo,
                        raw_audit_repo=self._raw_audit_repo,
                    ).execute(
                        SyncPriceRequest(
                            provider_id=price_provider.id,
                            asset_code=asset_code,
                            start=target_date - timedelta(days=max(request.price_lookback_days, 5)),
                            end=target_date,
                        )
                    )
                    details["prices"][asset_code] = {"sync": sync_result.to_dict()}
                except Exception as exc:
                    failed = True
                    blocked_reasons.append(f"{asset_code}: 历史价格同步失败: {exc}")
                    details["prices"][asset_code] = {
                        "sync": {"status": "failed", "error_message": str(exc)}
                    }

        quote_query = QueryLatestQuoteUseCase(self._quote_snapshot_repo)
        for asset_code in asset_codes:
            quote = quote_query.execute(
                LatestQuoteRequest(
                    asset_code=asset_code,
                    max_age_hours=request.quote_max_age_hours,
                )
            )
            if quote is None:
                reason = f"{asset_code}: 无可用最新行情。"
                blocked_reasons.append(reason)
                details["quotes"][asset_code] = {
                    "status": "blocked",
                    "blocked_reason": reason,
                }
            else:
                details["quotes"][asset_code] = quote.to_dict()
                if quote.must_not_use_for_decision:
                    blocked_reasons.append(
                        f"{asset_code}: {quote.blocked_reason or quote.freshness_status}"
                    )

            latest_bar = self._price_bar_repo.get_latest(asset_code)
            price_details = dict(details["prices"].get(asset_code) or {})
            price_details["latest_bar_date"] = (
                latest_bar.bar_date.isoformat() if latest_bar else None
            )
            if latest_bar is None:
                blocked_reasons.append(f"{asset_code}: 无可用历史价格。")
            elif latest_bar.bar_date < target_date:
                lag_days = (target_date - latest_bar.bar_date).days
                price_details["lag_days"] = lag_days
                if lag_days <= 3:
                    price_details["freshness_status"] = "latest_completed_session"
                else:
                    price_details["freshness_status"] = "stale"
                    blocked_reasons.append(
                        f"{asset_code}: 最新价格日线仅到 {latest_bar.bar_date.isoformat()}。"
                    )
            else:
                price_details["freshness_status"] = "fresh"
            details["prices"][asset_code] = price_details

        status_value = "ready"
        if failed:
            status_value = "failed"
        elif blocked_reasons:
            status_value = "blocked"
        return DecisionReliabilitySection(
            status=status_value,
            must_not_use_for_decision=failed or bool(blocked_reasons),
            blocked_reasons=blocked_reasons,
            details=details,
        )

    def _repair_pulse(
        self,
        request: DecisionReliabilityRepairRequest,
        target_date: date,
    ) -> DecisionReliabilitySection:
        if not request.repair_pulse:
            return DecisionReliabilitySection(
                status="skipped",
                must_not_use_for_decision=False,
                details={"message": "Pulse repair disabled by request."},
            )
        if self._pulse_refresher is None:
            return DecisionReliabilitySection(
                status="skipped",
                must_not_use_for_decision=True,
                blocked_reasons=["Pulse refresher 未配置。"],
            )

        try:
            snapshot = self._pulse_refresher(target_date)
        except Exception as exc:
            return DecisionReliabilitySection(
                status="failed",
                must_not_use_for_decision=True,
                blocked_reasons=[f"Pulse 重算失败: {exc}"],
                details={"error_message": str(exc)},
            )

        if snapshot is None:
            return DecisionReliabilitySection(
                status="blocked",
                must_not_use_for_decision=True,
                blocked_reasons=["Pulse 重算后仍无可用快照。"],
            )

        is_reliable = bool(getattr(snapshot, "is_reliable", False))
        stale_codes = [
            getattr(reading, "code", "")
            for reading in getattr(snapshot, "indicator_readings", []) or []
            if getattr(reading, "is_stale", False)
        ]
        observed_at = getattr(snapshot, "observed_at", None)
        details = {
            "observed_at": observed_at.isoformat() if observed_at else None,
            "data_source": getattr(snapshot, "data_source", ""),
            "is_reliable": is_reliable,
            "stale_indicator_count": getattr(snapshot, "stale_indicator_count", 0),
            "stale_indicator_codes": [code for code in stale_codes if code],
        }
        if is_reliable and not stale_codes:
            return DecisionReliabilitySection(
                status="ready",
                must_not_use_for_decision=False,
                details=details,
            )
        return DecisionReliabilitySection(
            status="blocked",
            must_not_use_for_decision=True,
            blocked_reasons=["Pulse 数据未通过 freshness/reliability 复验。"],
            details=details,
        )

    def _repair_alpha(
        self,
        request: DecisionReliabilityRepairRequest,
        target_date: date,
    ) -> DecisionReliabilitySection:
        if not request.repair_alpha:
            return DecisionReliabilitySection(
                status="skipped",
                must_not_use_for_decision=False,
                details={"message": "Alpha repair disabled by request."},
            )
        if request.portfolio_id is None:
            return DecisionReliabilitySection(
                status="blocked",
                must_not_use_for_decision=True,
                blocked_reasons=["Alpha readiness 需要 portfolio_id。"],
            )

        details: dict[str, Any] = {}
        blocked_reasons: list[str] = []
        failed = False
        if self._alpha_refresher is not None:
            try:
                repair_payload = self._alpha_refresher(
                    target_date,
                    request.portfolio_id,
                )
                details["repair"] = repair_payload
                if repair_payload.get("status") in {"failed", "queue_failed"}:
                    failed = True
                    message = (
                        repair_payload.get("qlib_result", {}).get("error_message")
                        or repair_payload.get("message")
                        or repair_payload.get("status")
                    )
                    blocked_reasons.append(f"Alpha 修复失败: {message}")
            except Exception as exc:
                failed = True
                blocked_reasons.append(f"Alpha 修复失败: {exc}")
                details["repair"] = {
                    "status": "failed",
                    "error_message": str(exc),
                }

        status_payload: dict[str, Any] = {}
        if self._alpha_status_reader is not None:
            try:
                status_payload = self._alpha_status_reader(
                    target_date,
                    request.portfolio_id,
                )
                details["readiness"] = status_payload
            except Exception as exc:
                failed = True
                blocked_reasons.append(f"Alpha readiness 读取失败: {exc}")
                details["readiness"] = {
                    "status": "failed",
                    "error_message": str(exc),
                }

        recommendation_ready = bool(status_payload.get("recommendation_ready", False))
        requested_trade_date = str(
            status_payload.get("requested_trade_date") or target_date.isoformat()
        )
        verified_asof_date = str(status_payload.get("verified_asof_date") or "")
        scope_verified = status_payload.get("scope_verification_status") == "verified"
        if not recommendation_ready:
            blocked_reasons.append("Dashboard Alpha 尚未产出 actionable 推荐。")
        if verified_asof_date and verified_asof_date != requested_trade_date:
            blocked_reasons.append(
                f"Alpha asof_date={verified_asof_date}，未达到请求交易日 {requested_trade_date}。"
            )
        if not scope_verified:
            blocked_reasons.append("Alpha scope 未通过 verified 校验。")

        status_value = "ready"
        if failed:
            status_value = "failed"
        elif blocked_reasons:
            status_value = "blocked"

        return DecisionReliabilitySection(
            status=status_value,
            must_not_use_for_decision=failed or bool(blocked_reasons),
            blocked_reasons=blocked_reasons,
            details=details,
        )

    def _select_macro_provider(self, indicator_code: str) -> ProviderConfig | None:
        if indicator_code in AKSHARE_MACRO_INDICATORS:
            provider = self._select_provider_by_types(
                ("akshare",),
                DataCapability.MACRO.value,
            )
            if provider is not None:
                return provider
        return self._select_provider_by_types(
            ("akshare", "tushare", "fred", "wind", "choice"),
            DataCapability.MACRO.value,
        )

    def _select_provider_by_types(
        self,
        source_types: tuple[str, ...],
        capability: str,
    ) -> ProviderConfig | None:
        providers = [
            provider
            for provider in self._provider_repo.list_all()
            if provider.is_active
            and provider.source_type in source_types
            and capability in _SOURCE_TYPE_CAPABILITIES.get(provider.source_type, ())
        ]
        providers.sort(
            key=lambda provider: (source_types.index(provider.source_type), provider.priority)
        )
        return providers[0] if providers else None

    @staticmethod
    def _normalize_unique(values: list[str] | tuple[str, ...]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = str(value).strip().upper()
            if item and item not in seen:
                normalized.append(item)
                seen.add(item)
        return normalized


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

    def _persist_provider_health_metric(
        self,
        config: ProviderConfig,
        *,
        capability: str,
        latency_ms: float,
        success: bool,
        error: str = "",
        recorded_at: datetime | None = None,
    ) -> None:
        recorded = recorded_at or datetime.now(timezone.utc)
        extra_config = dict(config.extra_config or {})
        capability_metrics = dict(extra_config.get("health_metrics") or {})
        metric = dict(capability_metrics.get(capability) or {})

        if success:
            success_count = int(metric.get("success_count", 0)) + 1
            previous_avg = metric.get("avg_latency_ms")
            if previous_avg is None:
                avg_latency_ms = round(latency_ms, 3)
            else:
                avg_latency_ms = round(
                    ((float(previous_avg) * (success_count - 1)) + latency_ms) / success_count,
                    3,
                )
            metric.update(
                {
                    "success_count": success_count,
                    "avg_latency_ms": avg_latency_ms,
                    "last_success_at": recorded.isoformat(),
                    "consecutive_failures": 0,
                    "last_status": "healthy",
                    "last_error": "",
                }
            )
            extra_config["provider_last_success_at"] = recorded.isoformat()
            provider_avg = extra_config.get("provider_avg_latency_ms")
            provider_success_count = int(extra_config.get("provider_success_count", 0)) + 1
            if provider_avg is None:
                extra_config["provider_avg_latency_ms"] = round(latency_ms, 3)
            else:
                extra_config["provider_avg_latency_ms"] = round(
                    ((float(provider_avg) * (provider_success_count - 1)) + latency_ms)
                    / provider_success_count,
                    3,
                )
            extra_config["provider_success_count"] = provider_success_count
            extra_config["provider_last_status"] = "healthy"
            extra_config["provider_last_error"] = ""
        else:
            metric.update(
                {
                    "consecutive_failures": int(metric.get("consecutive_failures", 0)) + 1,
                    "last_failure_at": recorded.isoformat(),
                    "last_status": "degraded",
                    "last_error": error,
                }
            )
            extra_config["provider_last_status"] = "degraded"
            extra_config["provider_last_error"] = error

        capability_metrics[capability] = metric
        extra_config["health_metrics"] = capability_metrics
        self._provider_repo.save(dataclasses.replace(config, extra_config=extra_config))


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
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            facts = provider.fetch_macro_series(request.indicator_code, request.start, request.end)
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._persist_provider_health_metric(
                config,
                capability="macro",
                latency_ms=latency_ms,
                success=True,
            )
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
            self._persist_provider_health_metric(
                config,
                capability="macro",
                latency_ms=latency_ms,
                success=False,
                error=str(exc),
            )
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
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            bars = provider.fetch_price_history(request.asset_code, request.start, request.end)
            stored_count = self._facts.bulk_upsert(bars)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._persist_provider_health_metric(
                config,
                capability="historical_price",
                latency_ms=latency_ms,
                success=True,
            )
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
            self._persist_provider_health_metric(
                config,
                capability="historical_price",
                latency_ms=latency_ms,
                success=False,
                error=str(exc),
            )
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "historical_price",
                    {
                        "asset_code": request.asset_code,
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
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            quotes = provider.fetch_quote_snapshots(request.asset_codes)
            stored_count = self._facts.bulk_upsert(quotes)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._persist_provider_health_metric(
                config,
                capability="realtime_quote",
                latency_ms=latency_ms,
                success=True,
            )
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
            self._persist_provider_health_metric(
                config,
                capability="realtime_quote",
                latency_ms=latency_ms,
                success=False,
                error=str(exc),
            )
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "realtime_quote",
                    {"asset_codes": request.asset_codes},
                    "error",
                    0,
                    latency_ms,
                    str(exc),
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
                    provider.provider_name(),
                    "fund_nav",
                    {
                        "fund_code": request.fund_code,
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
                    provider.provider_name(),
                    "financial",
                    {"asset_code": request.asset_code, "periods": request.periods},
                    "error",
                    0,
                    latency_ms,
                    str(exc),
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
                    provider.provider_name(),
                    "valuation",
                    {
                        "asset_code": request.asset_code,
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
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "sector_membership",
                    params,
                    "ok",
                    stored_count,
                    latency_ms,
                )
            )
            return SyncResult(
                "sector_membership", provider.provider_name(), stored_count, "success"
            )
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "sector_membership",
                    params,
                    "error",
                    0,
                    latency_ms,
                    str(exc),
                )
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
                _build_sync_audit(
                    provider.provider_name(), "news", params, "ok", stored_count, latency_ms
                )
            )
            return SyncResult("news", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(), "news", params, "error", 0, latency_ms, str(exc)
                )
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
                _build_sync_audit(
                    provider.provider_name(), "capital_flow", params, "ok", stored_count, latency_ms
                )
            )
            return SyncResult("capital_flow", provider.provider_name(), stored_count, "success")
        except Exception as exc:
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "capital_flow",
                    params,
                    "error",
                    0,
                    latency_ms,
                    str(exc),
                )
            )
            raise
