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
    CreateIndicatorCatalogRequest,
    CreateIndicatorUnitRuleRequest,
    CreatePublisherCatalogRequest,
    CreateProviderRequest,
    DecisionReliabilityRepairReport,
    DecisionReliabilityRepairRequest,
    DecisionReliabilitySection,
    IndicatorCatalogResponse,
    IndicatorUnitRuleResponse,
    LatestQuoteRequest,
    MacroDataPoint,
    MacroSeriesRequest,
    MacroSeriesResponse,
    PriceBarResponse,
    PriceHistoryRequest,
    PublisherCatalogResponse,
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
    UpdateIndicatorCatalogRequest,
    UpdateIndicatorUnitRuleRequest,
    UpdatePublisherCatalogRequest,
    UpdateProviderRequest,
)
from apps.data_center.domain.entities import (
    ConnectionTestResult,
    IndicatorCatalog,
    IndicatorUnitRule,
    PublisherCatalog,
    ProviderConfig,
    RawAudit,
)
from apps.data_center.domain.enums import DataCapability, FinancialPeriodType
from apps.data_center.domain.protocols import (
    AssetRepositoryProtocol,
    CapitalFlowRepositoryProtocol,
    ConnectionTesterProtocol,
    FinancialFactRepositoryProtocol,
    FundNavRepositoryProtocol,
    IndicatorCatalogRepositoryProtocol,
    IndicatorUnitRuleRepositoryProtocol,
    MacroGovernanceRepositoryProtocol,
    MacroFactRepositoryProtocol,
    NewsRepositoryProtocol,
    PriceBarRepositoryProtocol,
    PublisherCatalogRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    QuoteSnapshotRepositoryProtocol,
    RawAuditRepositoryProtocol,
    RegistryProtocol,
    SectorMembershipRepositoryProtocol,
    UnifiedDataProviderProtocol,
    ValuationFactRepositoryProtocol,
)
from apps.data_center.domain.rules import (
    convert_currency_value,
    get_macro_age_days,
    is_macro_observation_stale,
    is_stale,
    normalize_asset_code,
)

if TYPE_CHECKING:
    from apps.data_center.domain.entities import ProviderHealthSnapshot

logger = logging.getLogger(__name__)
RECOVERABLE_DATA_CENTER_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)
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


def _publisher_to_response(publisher: PublisherCatalog) -> PublisherCatalogResponse:
    return PublisherCatalogResponse(
        code=publisher.code,
        canonical_name=publisher.canonical_name,
        publisher_class=publisher.publisher_class,
        aliases=list(publisher.aliases),
        canonical_name_en=publisher.canonical_name_en,
        country_code=publisher.country_code,
        website=publisher.website,
        is_active=publisher.is_active,
        description=publisher.description,
    )


def _catalog_to_response(
    catalog: IndicatorCatalog,
    *,
    default_rule: IndicatorUnitRule | None = None,
) -> IndicatorCatalogResponse:
    return IndicatorCatalogResponse(
        code=catalog.code,
        name_cn=catalog.name_cn,
        name_en=catalog.name_en,
        description=catalog.description,
        category=catalog.category,
        default_period_type=catalog.default_period_type,
        is_active=catalog.is_active,
        extra=catalog.extra,
        default_rule=default_rule.to_dict() if default_rule else None,
    )


def _unit_rule_to_response(rule: IndicatorUnitRule) -> IndicatorUnitRuleResponse:
    return IndicatorUnitRuleResponse(
        id=rule.id,
        indicator_code=rule.indicator_code,
        source_type=rule.source_type,
        dimension_key=rule.dimension_key,
        original_unit=rule.original_unit,
        storage_unit=rule.storage_unit,
        display_unit=rule.display_unit,
        multiplier_to_storage=rule.multiplier_to_storage,
        is_active=rule.is_active,
        priority=rule.priority,
        description=rule.description,
    )


def _storage_value_to_display_value(
    value: float,
    *,
    storage_unit: str,
    display_unit: str,
    multiplier_to_storage: float,
) -> float:
    converted_value, converted_unit = convert_currency_value(
        value,
        storage_unit,
        display_unit,
    )
    if converted_unit == display_unit:
        return converted_value
    if multiplier_to_storage == 0:
        return value
    return value / multiplier_to_storage


def _dedupe_string_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized:
            continue
        key = normalized.upper()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


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


class ManagePublisherCatalogUseCase:
    """CRUD operations for provenance publisher definitions."""

    def __init__(self, repo: PublisherCatalogRepositoryProtocol) -> None:
        self._repo = repo

    def list_all(self, *, active_only: bool = False) -> list[PublisherCatalogResponse]:
        publishers = self._repo.list_active() if active_only else self._repo.list_all()
        return [_publisher_to_response(item) for item in publishers]

    def get(self, code: str) -> PublisherCatalogResponse | None:
        publisher = self._repo.get_by_code(code)
        return _publisher_to_response(publisher) if publisher else None

    def create(self, request: CreatePublisherCatalogRequest) -> PublisherCatalogResponse:
        publisher = PublisherCatalog(
            code=request.code.strip().upper(),
            canonical_name=request.canonical_name,
            publisher_class=request.publisher_class,
            aliases=list(request.aliases),
            canonical_name_en=request.canonical_name_en,
            country_code=request.country_code,
            website=request.website,
            is_active=request.is_active,
            description=request.description,
        )
        saved = self._repo.upsert(publisher)
        return _publisher_to_response(saved)

    def update(self, request: UpdatePublisherCatalogRequest) -> PublisherCatalogResponse | None:
        existing = self._repo.get_by_code(request.code)
        if existing is None:
            return None
        updated = PublisherCatalog(
            code=existing.code.strip().upper(),
            canonical_name=(
                request.canonical_name
                if request.canonical_name is not None
                else existing.canonical_name
            ),
            publisher_class=(
                request.publisher_class
                if request.publisher_class is not None
                else existing.publisher_class
            ),
            aliases=request.aliases if request.aliases is not None else list(existing.aliases),
            canonical_name_en=(
                request.canonical_name_en
                if request.canonical_name_en is not None
                else existing.canonical_name_en
            ),
            country_code=(
                request.country_code if request.country_code is not None else existing.country_code
            ),
            website=request.website if request.website is not None else existing.website,
            is_active=request.is_active if request.is_active is not None else existing.is_active,
            description=(
                request.description if request.description is not None else existing.description
            ),
        )
        saved = self._repo.upsert(updated)
        return _publisher_to_response(saved)

    def delete(self, code: str) -> bool:
        if self._repo.get_by_code(code) is None:
            return False
        self._repo.delete(code)
        return True


class ManageIndicatorCatalogUseCase:
    """CRUD operations for indicator catalog definitions."""

    def __init__(
        self,
        repo: IndicatorCatalogRepositoryProtocol,
        unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
    ) -> None:
        self._repo = repo
        self._unit_rules = unit_rule_repo

    def list_all(self, *, active_only: bool = False) -> list[IndicatorCatalogResponse]:
        catalogs = self._repo.list_active() if active_only else self._repo.list_all()
        return [
            _catalog_to_response(
                catalog,
                default_rule=self._unit_rules.resolve_active_rule(catalog.code),
            )
            for catalog in catalogs
        ]

    def get(self, code: str) -> IndicatorCatalogResponse | None:
        catalog = self._repo.get_by_code(code)
        if catalog is None:
            return None
        return _catalog_to_response(
            catalog,
            default_rule=self._unit_rules.resolve_active_rule(code),
        )

    def create(self, request: CreateIndicatorCatalogRequest) -> IndicatorCatalogResponse:
        catalog = IndicatorCatalog(
            code=request.code,
            name_cn=request.name_cn,
            name_en=request.name_en,
            description=request.description,
            default_period_type=request.default_period_type,
            category=request.category,
            is_active=request.is_active,
            extra=request.extra,
        )
        saved = self._repo.upsert(catalog)
        return _catalog_to_response(saved)

    def update(self, request: UpdateIndicatorCatalogRequest) -> IndicatorCatalogResponse | None:
        existing = self._repo.get_by_code(request.code)
        if existing is None:
            return None

        updated = IndicatorCatalog(
            code=existing.code,
            name_cn=request.name_cn if request.name_cn is not None else existing.name_cn,
            name_en=request.name_en if request.name_en is not None else existing.name_en,
            description=(
                request.description if request.description is not None else existing.description
            ),
            default_period_type=(
                request.default_period_type
                if request.default_period_type is not None
                else existing.default_period_type
            ),
            category=request.category if request.category is not None else existing.category,
            is_active=request.is_active if request.is_active is not None else existing.is_active,
            extra=request.extra if request.extra is not None else existing.extra,
        )
        saved = self._repo.upsert(updated)
        return _catalog_to_response(
            saved,
            default_rule=self._unit_rules.resolve_active_rule(saved.code),
        )

    def delete(self, code: str) -> bool:
        if self._repo.get_by_code(code) is None:
            return False
        self._repo.delete(code)
        return True


class ManageIndicatorUnitRuleUseCase:
    """CRUD operations for indicator unit-governance rules."""

    def __init__(
        self,
        catalog_repo: IndicatorCatalogRepositoryProtocol,
        repo: IndicatorUnitRuleRepositoryProtocol,
    ) -> None:
        self._catalog = catalog_repo
        self._repo = repo

    def list_by_indicator(self, indicator_code: str) -> list[IndicatorUnitRuleResponse]:
        return [
            _unit_rule_to_response(rule) for rule in self._repo.list_by_indicator(indicator_code)
        ]

    def get(self, rule_id: int) -> IndicatorUnitRuleResponse | None:
        rule = self._repo.get_by_id(rule_id)
        return _unit_rule_to_response(rule) if rule else None

    def create(self, request: CreateIndicatorUnitRuleRequest) -> IndicatorUnitRuleResponse:
        if self._catalog.get_by_code(request.indicator_code) is None:
            raise ValueError(f"Unknown indicator code: {request.indicator_code}")
        rule = IndicatorUnitRule(
            id=None,
            indicator_code=request.indicator_code,
            source_type=request.source_type,
            dimension_key=request.dimension_key,
            original_unit=request.original_unit,
            storage_unit=request.storage_unit,
            display_unit=request.display_unit,
            multiplier_to_storage=request.multiplier_to_storage,
            is_active=request.is_active,
            priority=request.priority,
            description=request.description,
        )
        saved = self._repo.upsert(rule)
        return _unit_rule_to_response(saved)

    def update(self, request: UpdateIndicatorUnitRuleRequest) -> IndicatorUnitRuleResponse | None:
        existing = self._repo.get_by_id(request.rule_id)
        if existing is None:
            return None

        next_indicator_code = request.indicator_code or existing.indicator_code
        if self._catalog.get_by_code(next_indicator_code) is None:
            raise ValueError(f"Unknown indicator code: {next_indicator_code}")

        updated = IndicatorUnitRule(
            id=existing.id,
            indicator_code=next_indicator_code,
            source_type=(
                request.source_type if request.source_type is not None else existing.source_type
            ),
            dimension_key=(
                request.dimension_key
                if request.dimension_key is not None
                else existing.dimension_key
            ),
            original_unit=(
                request.original_unit
                if request.original_unit is not None
                else existing.original_unit
            ),
            storage_unit=(
                request.storage_unit if request.storage_unit is not None else existing.storage_unit
            ),
            display_unit=(
                request.display_unit if request.display_unit is not None else existing.display_unit
            ),
            multiplier_to_storage=(
                request.multiplier_to_storage
                if request.multiplier_to_storage is not None
                else existing.multiplier_to_storage
            ),
            is_active=request.is_active if request.is_active is not None else existing.is_active,
            priority=request.priority if request.priority is not None else existing.priority,
            description=(
                request.description if request.description is not None else existing.description
            ),
        )
        saved = self._repo.upsert(updated)
        return _unit_rule_to_response(saved)

    def delete(self, rule_id: int) -> bool:
        if self._repo.get_by_id(rule_id) is None:
            return False
        self._repo.delete(rule_id)
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
        unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
        publisher_repo: PublisherCatalogRepositoryProtocol | None = None,
    ) -> None:
        self._facts = fact_repo
        self._catalog = catalog_repo
        self._unit_rules = unit_rule_repo
        self._publishers = publisher_repo

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
        description = catalog.description if catalog else ""
        catalog_extra = dict(catalog.extra or {}) if catalog else {}
        series_semantics = str(catalog_extra.get("series_semantics") or "")
        paired_indicator_code = str(catalog_extra.get("paired_indicator_code") or "")
        provenance_class = str(catalog_extra.get("provenance_class") or "").strip()
        provenance_label = _provenance_label_for_class(provenance_class)
        publisher_code, publisher_codes = self._extract_publisher_codes(catalog_extra)
        publisher = self._resolve_publisher_display_name(
            publisher_code=publisher_code,
            publisher_codes=publisher_codes,
            explicit_publisher=str(catalog_extra.get("publisher") or "").strip(),
        )
        access_channel = str(catalog_extra.get("access_channel") or "").strip()
        derivation_method = str(catalog_extra.get("derivation_method") or "").strip()
        upstream_indicator_codes = [
            str(code).strip()
            for code in (catalog_extra.get("upstream_indicator_codes") or [])
            if str(code).strip()
        ]
        is_derived = provenance_class == "derived"
        decision_grade_enabled = self._is_decision_grade_enabled(
            provenance_class=provenance_class,
            catalog_extra=catalog_extra,
        )

        data_points: list[MacroDataPoint]
        data_source = "none"
        freshness_status = "missing"
        decision_grade = "blocked"
        must_not_use_for_decision = True
        blocked_reason = "当前无可用宏观数据。"
        if facts:
            data_source = "data_center_fact"
            as_of_date = request.end
            data_points = [
                self._build_macro_data_point(
                    indicator_code=f.indicator_code,
                    reporting_period=f.reporting_period,
                    value=f.value,
                    unit=f.unit,
                    extra=f.extra or {},
                    source=f.source,
                    quality=f.quality.value,
                    published_at=f.published_at,
                    period_type=period_type,
                    as_of_date=as_of_date,
                    catalog_extra=catalog_extra,
                )
                for f in facts
            ]
        else:
            data_points = []

        if data_points:
            latest = data_points[0]
            if latest.is_stale:
                freshness_status = "stale"
                decision_grade = "degraded"
                blocked_reason = (
                    "最新宏观数据已超过 freshness 阈值，当前结果仅可用于研究，不可直接用于决策。"
                )
            elif not decision_grade_enabled:
                freshness_status = "fresh"
                decision_grade = "research_only"
                blocked_reason = self._build_provenance_blocked_reason(
                    provenance_class=provenance_class,
                    derivation_method=derivation_method,
                )
            else:
                freshness_status = "fresh"
                decision_grade = "decision_safe"
                must_not_use_for_decision = False
                blocked_reason = ""

        latest_reporting_period = data_points[0].reporting_period if data_points else None
        latest_published_at = data_points[0].published_at if data_points else None
        latest_quality = data_points[0].quality if data_points else ""

        return MacroSeriesResponse(
            indicator_code=request.indicator_code,
            name_cn=name_cn,
            period_type=period_type,
            description=description,
            series_semantics=series_semantics,
            paired_indicator_code=paired_indicator_code,
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
            provenance_class=provenance_class,
            provenance_label=provenance_label,
            publisher=publisher,
            publisher_code=publisher_code,
            publisher_codes=publisher_codes,
            access_channel=access_channel or (data_points[0].access_channel if data_points else ""),
            derivation_method=derivation_method,
            upstream_indicator_codes=upstream_indicator_codes,
            is_derived=is_derived,
        )

    def _build_macro_data_point(
        self,
        *,
        indicator_code: str,
        reporting_period: date,
        value: float,
        unit: str,
        extra: dict[str, Any],
        source: str,
        quality: str,
        published_at: date | None,
        period_type: str,
        as_of_date: date | None = None,
        catalog_extra: dict[str, Any] | None = None,
    ) -> MacroDataPoint:
        catalog_meta = dict(catalog_extra or {})
        age_days = get_macro_age_days(reporting_period, published_at, as_of_date=as_of_date)
        point_is_stale = is_macro_observation_stale(
            reporting_period,
            published_at,
            period_type=period_type,
            as_of_date=as_of_date,
        )
        provenance_class = str(catalog_meta.get("provenance_class") or "").strip()
        derivation_method = str(catalog_meta.get("derivation_method") or "").strip()
        publisher_code, publisher_codes = self._extract_publisher_codes(catalog_meta)
        publisher = self._resolve_publisher_display_name(
            publisher_code=publisher_code,
            publisher_codes=publisher_codes,
            explicit_publisher=str(catalog_meta.get("publisher") or "").strip(),
        )
        is_derived = provenance_class == "derived"
        decision_grade_enabled = self._is_decision_grade_enabled(
            provenance_class=provenance_class,
            catalog_extra=catalog_meta,
        )
        if point_is_stale:
            decision_grade = "degraded"
        elif not decision_grade_enabled:
            decision_grade = "research_only"
        else:
            decision_grade = "decision_safe"

        original_unit = str(extra.get("original_unit") or "")
        display_unit = str(extra.get("display_unit") or original_unit or unit)
        try:
            multiplier_to_storage = float(extra.get("multiplier_to_storage") or 1.0)
        except (TypeError, ValueError):
            multiplier_to_storage = 1.0

        if not display_unit or not original_unit:
            matched_rule = self._unit_rules.resolve_active_rule(
                indicator_code,
                source_type=str(extra.get("source_type") or ""),
                original_unit=original_unit or None,
            )
            if matched_rule is not None:
                original_unit = original_unit or matched_rule.original_unit
                display_unit = display_unit or matched_rule.display_unit or original_unit or unit
                multiplier_to_storage = matched_rule.multiplier_to_storage

        display_value = _storage_value_to_display_value(
            value,
            storage_unit=unit,
            display_unit=display_unit or unit,
            multiplier_to_storage=multiplier_to_storage,
        )

        return MacroDataPoint(
            indicator_code=indicator_code,
            reporting_period=reporting_period,
            value=value,
            unit=unit,
            display_value=display_value,
            display_unit=display_unit or unit,
            original_unit=original_unit or display_unit or unit,
            source=source,
            quality=quality,
            published_at=published_at,
            age_days=age_days,
            is_stale=point_is_stale,
            freshness_status="stale" if point_is_stale else "fresh",
            decision_grade=decision_grade,
            provenance_class=provenance_class,
            provenance_label=_provenance_label_for_class(provenance_class),
            publisher=publisher,
            publisher_code=publisher_code,
            publisher_codes=publisher_codes,
            access_channel=str(
                catalog_meta.get("access_channel") or extra.get("source_type") or source
            ),
            derivation_method=derivation_method,
            is_derived=is_derived,
        )

    @staticmethod
    def _extract_publisher_codes(catalog_extra: dict[str, Any]) -> tuple[str, list[str]]:
        explicit_code = str(catalog_extra.get("publisher_code") or "").strip().upper()
        explicit_codes = _dedupe_string_list(
            [str(code).strip().upper() for code in (catalog_extra.get("publisher_codes") or [])]
        )
        publisher_codes = explicit_codes or ([explicit_code] if explicit_code else [])
        publisher_code = explicit_code or (publisher_codes[0] if publisher_codes else "")
        return publisher_code, publisher_codes

    def _resolve_publisher_display_name(
        self,
        *,
        publisher_code: str,
        publisher_codes: list[str],
        explicit_publisher: str,
    ) -> str:
        if self._publishers is None:
            return explicit_publisher

        resolved_names: list[str] = []
        seen: set[str] = set()
        for code in publisher_codes:
            publisher = self._publishers.get_by_code(code)
            if publisher is None:
                continue
            name = publisher.canonical_name.strip()
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            resolved_names.append(name)

        if resolved_names:
            return "/".join(resolved_names)

        if publisher_code:
            publisher = self._publishers.get_by_code(publisher_code)
            if publisher is not None and publisher.canonical_name.strip():
                return publisher.canonical_name.strip()

        return explicit_publisher

    @staticmethod
    def _is_decision_grade_enabled(
        *,
        provenance_class: str,
        catalog_extra: dict[str, Any],
    ) -> bool:
        explicit = catalog_extra.get("decision_grade_enabled")
        if explicit is None:
            return provenance_class != "derived"
        return bool(explicit)

    @staticmethod
    def _build_provenance_blocked_reason(
        *,
        provenance_class: str,
        derivation_method: str,
    ) -> str:
        if provenance_class == "derived":
            if derivation_method:
                return (
                    "当前序列属于系统衍生数据，默认仅供研究，不可直接用于决策。"
                    f"派生方法：{derivation_method}"
                )
            return "当前序列属于系统衍生数据，默认仅供研究，不可直接用于决策。"
        return "当前序列 provenance 未通过决策级校验，仅可用于研究。"


def _provenance_label_for_class(provenance_class: str) -> str:
    return {
        "official": "官方数据",
        "authoritative_third_party": "权威转引",
        "derived": "系统衍生",
    }.get(provenance_class, "")


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
        indicator_unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
        price_bar_repo: PriceBarRepositoryProtocol,
        quote_snapshot_repo: QuoteSnapshotRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        pulse_refresher: Callable[[date], Any] | None = None,
        alpha_refresher: Callable[[date, int | None], dict[str, Any]] | None = None,
        alpha_status_reader: Callable[[date, int | None], dict[str, Any]] | None = None,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_factory = provider_factory
        self._macro_fact_repo = macro_fact_repo
        self._indicator_catalog_repo = indicator_catalog_repo
        self._indicator_unit_rule_repo = indicator_unit_rule_repo
        self._price_bar_repo = price_bar_repo
        self._quote_snapshot_repo = quote_snapshot_repo
        self._raw_audit_repo = raw_audit_repo
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
                    catalog_repo=self._indicator_catalog_repo,
                    unit_rule_repo=self._indicator_unit_rule_repo,
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
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                failed = True
                blocked_reasons.append(f"{indicator_code}: 同步失败: {exc}")
                indicator_details["sync"] = {
                    "status": "failed",
                    "error_message": str(exc),
                }

            query = QueryMacroSeriesUseCase(
                self._macro_fact_repo,
                self._indicator_catalog_repo,
                self._indicator_unit_rule_repo,
            ).execute(
                MacroSeriesRequest(
                    indicator_code=indicator_code,
                    end=target_date,
                    limit=1,
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
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
                except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
        latest_completed_session_result = (
            bool(status_payload.get("latest_completed_session_result", False))
            or status_payload.get("freshness_status") == "latest_completed_session"
        )
        if not recommendation_ready:
            blocked_reasons.append("Dashboard Alpha 尚未产出 actionable 推荐。")
        if (
            verified_asof_date
            and verified_asof_date != requested_trade_date
            and not latest_completed_session_result
        ):
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


class RunMacroGovernanceActionUseCase:
    """Execute macro governance repair actions through governed repositories/use cases."""

    DEFAULT_SCOPE = "macro_console"

    def __init__(
        self,
        governance_repo: MacroGovernanceRepositoryProtocol,
        provider_repo: ProviderConfigRepositoryProtocol,
        sync_macro_runner: Callable[[SyncMacroRequest], SyncResult],
    ) -> None:
        self._governance_repo = governance_repo
        self._provider_repo = provider_repo
        self._sync_macro_runner = sync_macro_runner

    def execute(self, action: str) -> dict[str, Any]:
        if action == "canonicalize_sources":
            repair = self._governance_repo.canonicalize_sources(scope=self.DEFAULT_SCOPE)
            return {
                "action": action,
                "label": "统一 source 别名",
                "status": "success",
                "details": repair,
            }

        if action == "normalize_units":
            details = self._normalize_units()
            return {
                "action": action,
                "label": "重跑单位标准化",
                "status": "success",
                "details": details,
            }

        if action == "sync_missing_series":
            details = self._sync_missing_series()
            return {
                "action": action,
                "label": "补同步缺失序列",
                "status": "success",
                "details": details,
            }

        if action == "run_full_repair":
            source_details = self._governance_repo.canonicalize_sources(scope=self.DEFAULT_SCOPE)
            normalize_details = self._normalize_units()
            sync_details = self._sync_missing_series()
            return {
                "action": action,
                "label": "执行完整治理",
                "status": "success",
                "details": {
                    "source": source_details,
                    "normalize": normalize_details,
                    "sync": sync_details,
                },
            }

        raise ValueError(f"Unsupported governance action: {action}")

    def _normalize_units(self) -> dict[str, Any]:
        indicator_codes = self._governance_repo.list_governed_indicator_codes(scope=self.DEFAULT_SCOPE)
        details = self._governance_repo.normalize_macro_fact_units(
            indicator_codes=indicator_codes,
            dry_run=False,
        )
        return {
            "indicator_codes": indicator_codes,
            **details,
        }

    def _sync_missing_series(self) -> dict[str, Any]:
        payload = self._governance_repo.build_snapshot(scope=self.DEFAULT_SCOPE)
        supported_sync_codes = set(payload.get("supported_sync_codes") or [])
        indicator_rows = payload.get("indicator_rows") or []
        target_rows = [
            row
            for row in indicator_rows
            if "missing_supported" in (row.get("tags") or [])
            and row.get("code") in supported_sync_codes
        ]
        if not target_rows:
            return {
                "indicator_codes": [],
                "sync_runs": [],
                "message": "No supported missing indicator codes to sync.",
            }

        target_date = datetime.now(timezone.utc).date()
        start_date = target_date - timedelta(days=365 * 10)
        sync_runs: list[dict[str, Any]] = []

        for row in target_rows:
            indicator_code = str(row.get("code") or "").strip()
            source_type = str(row.get("sync_source_type") or "").strip()
            if not indicator_code:
                continue
            if not source_type:
                raise ValueError(
                    f"Governed indicator {indicator_code} is missing governance_sync_source_type"
                )

            provider_id = self._resolve_macro_provider_id(source_type)
            sync_result = self._sync_macro_runner(
                SyncMacroRequest(
                    provider_id=provider_id,
                    indicator_code=indicator_code,
                    start=start_date,
                    end=target_date,
                )
            )
            sync_runs.append(
                {
                    "indicator_code": indicator_code,
                    "source_type": source_type,
                    "provider_id": provider_id,
                    "provider_name": sync_result.provider_name,
                    "stored_count": sync_result.stored_count,
                    "status": sync_result.status,
                }
            )

        return {
            "indicator_codes": [
                str(row.get("code") or "").strip()
                for row in target_rows
                if row.get("code")
            ],
            "sync_runs": sync_runs,
        }

    def _resolve_macro_provider_id(self, source_type: str) -> int:
        providers = [
            provider
            for provider in self._provider_repo.list_all()
            if provider.id is not None
            and provider.is_active
            and provider.source_type == source_type
            and DataCapability.MACRO.value in _SOURCE_TYPE_CAPABILITIES.get(provider.source_type, ())
        ]
        providers.sort(key=lambda provider: provider.priority)
        if not providers:
            raise ValueError(f"No active macro provider configured for source_type={source_type}")
        return int(providers[0].id)


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

    @staticmethod
    def _normalize_fact_source(
        fact,
        *,
        source_type: str,
        provider_name: str,
    ):
        updates: dict[str, Any] = {"source": source_type}
        if hasattr(fact, "extra"):
            next_extra = dict(getattr(fact, "extra", {}) or {})
            next_extra["source_type"] = source_type
            next_extra.setdefault("provider_name", provider_name)
            updates["extra"] = next_extra
        return dataclasses.replace(fact, **updates)

    @classmethod
    def _normalize_fact_sources(
        cls,
        facts: list[Any],
        *,
        source_type: str,
        provider_name: str,
    ) -> list[Any]:
        return [
            cls._normalize_fact_source(
                fact,
                source_type=source_type,
                provider_name=provider_name,
            )
            for fact in facts
        ]

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
        catalog_repo: IndicatorCatalogRepositoryProtocol,
        unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_factory, raw_audit_repo)
        self._facts = fact_repo
        self._catalog = catalog_repo
        self._unit_rules = unit_rule_repo

    def _normalize_macro_facts(
        self,
        *,
        indicator_code: str,
        source_type: str,
        provider_name: str,
        facts: list,
    ) -> list:
        if self._catalog.get_by_code(indicator_code) is None:
            raise ValueError(f"Indicator catalog missing for {indicator_code}")

        normalized = []
        for fact in facts:
            extra = dict(getattr(fact, "extra", {}) or {})
            original_unit = str(extra.get("original_unit") or fact.unit or "")
            rule = self._unit_rules.resolve_active_rule(
                indicator_code,
                source_type=source_type,
                original_unit=original_unit,
            )
            if rule is None:
                raise ValueError(
                    f"Indicator unit rule missing for {indicator_code}@{source_type} unit={original_unit!r}"
                )

            extra.update(
                {
                    "source_type": source_type,
                    "provider_name": provider_name,
                    "original_unit": original_unit,
                    "display_unit": rule.display_unit,
                    "dimension_key": rule.dimension_key,
                    "multiplier_to_storage": rule.multiplier_to_storage,
                    "matched_rule_id": rule.id,
                }
            )
            normalized.append(
                dataclasses.replace(
                    fact,
                    value=float(fact.value) * float(rule.multiplier_to_storage),
                    source=source_type,
                    unit=rule.storage_unit,
                    extra=extra,
                )
            )
        return normalized

    def execute(self, request: SyncMacroRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            facts = provider.fetch_macro_series(request.indicator_code, request.start, request.end)
            normalized = self._normalize_macro_facts(
                indicator_code=request.indicator_code,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
                facts=facts,
            )
            stored_count = self._facts.bulk_upsert(normalized)
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
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
            bars = self._normalize_fact_sources(
                bars,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
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
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
            quotes = self._normalize_fact_sources(
                quotes,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
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
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            facts = provider.fetch_fund_nav(request.fund_code, request.start, request.end)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
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
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            facts = provider.fetch_financials(request.asset_code, periods=request.periods)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
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
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        try:
            facts = provider.fetch_valuations(request.asset_code, request.start, request.end)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
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
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
        config, provider = self._get_provider(request.provider_id)
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
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
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
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        params = {"asset_code": request.asset_code, "limit": request.limit}
        try:
            facts = provider.fetch_news(request.asset_code, limit=request.limit)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_insert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(), "news", params, "ok", stored_count, latency_ms
                )
            )
            return SyncResult("news", provider.provider_name(), stored_count, "success")
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(timezone.utc)
        params = {"asset_code": request.asset_code, "period": request.period}
        try:
            facts = provider.fetch_capital_flows(request.asset_code, period=request.period)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(), "capital_flow", params, "ok", stored_count, latency_ms
                )
            )
            return SyncResult("capital_flow", provider.provider_name(), stored_count, "success")
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
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
