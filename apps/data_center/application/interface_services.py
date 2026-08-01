"""Application-side dependency builders for data_center interface endpoints."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any, Protocol, cast

from apps.data_center.application.dtos import (
    LatestQuoteRequest,
    SyncNewsRequest,
    SyncQuoteRequest,
    SyncResult,
)
from apps.data_center.application.on_demand import OnDemandDataCenterService
from apps.data_center.application.provider_capabilities import SOURCE_TYPE_CAPABILITIES
from apps.data_center.application.provider_health import build_capability_health_payload
from apps.data_center.composition import (
    AssetRepository,
    CapitalFlowRepository,
    DataProviderSettingsRepository,
    FinancialFactRepository,
    FundNavRepository,
    IndicatorCatalogRepository,
    IndicatorUnitRuleRepository,
    MacroFactRepository,
    MacroGovernanceRepository,
    MarketThermometerConfigRepository,
    MarketThermometerSnapshotRepository,
    MarketThermometerUserOverrideRepository,
    NewsRepository,
    PriceBarRepository,
    ProductionCoverageUniverseConfigRepository,
    ProviderConfigRepository,
    PublisherCatalogRepository,
    QuoteSnapshotRepository,
    RawAuditRepository,
    SectorMembershipRepository,
    ValuationFactRepository,
    build_provider_registry_for_repo,
    get_provider_registry,
    run_data_center_connection_test,
)
from apps.data_center.domain.entities import (
    ConnectionTestResult,
    DataProviderSettings,
    ProductionCoverageUniverseConfig,
    ProviderConfig,
)
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import ProviderRegistryProtocol
from apps.task_monitor.application.tracking import record_pending_task
from core.exceptions import DataFetchError

from .business_runtime_gateway import fetch_latest_prices as _fetch_latest_prices
from .business_runtime_gateway import load_alpha_homepage_data as _load_alpha_homepage_data
from .business_runtime_gateway import queue_alpha_score_prediction as _queue_alpha_score_prediction
from .business_runtime_gateway import refresh_pulse_snapshot as _refresh_pulse_snapshot
from .business_runtime_gateway import (
    resolve_portfolio_alpha_scope as _resolve_portfolio_alpha_scope,
)
from .business_runtime_gateway import (
    run_alpha_score_prediction_now as _run_alpha_score_prediction_now,
)
from .market_thermometer import (
    CalculateMarketThermometerUseCase,
    ImportInvestorAccountsUseCase,
    ManageMarketThermometerConfigUseCase,
    ManageMarketThermometerUserOverrideUseCase,
    SyncMarketThermometerInputsUseCase,
    build_market_thermometer_override_payload,
)
from .provider_connection_workflow import RunProviderConnectionTestUseCase
from .use_cases import (
    DEFAULT_DECISION_ASSET_CODES,
    ManageIndicatorCatalogUseCase,
    ManageIndicatorUnitRuleUseCase,
    ManageProviderConfigUseCase,
    ManagePublisherCatalogUseCase,
    QueryCapitalFlowsUseCase,
    QueryFinancialsUseCase,
    QueryFundNavUseCase,
    QueryLatestQuoteUseCase,
    QueryMacroSeriesUseCase,
    QueryNewsUseCase,
    QueryPriceHistoryUseCase,
    QuerySectorConstituentsUseCase,
    QueryValuationsUseCase,
    RepairDecisionDataReliabilityUseCase,
    ResolveAssetUseCase,
    RunMacroGovernanceActionUseCase,
    SyncCapitalFlowUseCase,
    SyncFinancialUseCase,
    SyncFundNavUseCase,
    SyncMacroBatchUseCase,
    SyncMacroUseCase,
    SyncNewsUseCase,
    SyncPriceUseCase,
    SyncQuoteUseCase,
    SyncSectorMembershipUseCase,
    SyncValuationUseCase,
)


class _AlphaScopeProtocol(Protocol):
    """Minimum Alpha scope projection consumed by repair workflows."""

    instrument_codes: Sequence[str]
    universe_id: str
    scope_hash: str

    def to_dict(self) -> dict[str, Any]: ...


class _AlphaScopeResolutionProtocol(Protocol):
    """Minimum result returned by the registered Alpha scope resolver."""

    scope: _AlphaScopeProtocol
    portfolio_id: int | None


class _AlphaHomepageDataProtocol(Protocol):
    """Minimum Dashboard Alpha payload consumed by readiness checks."""

    meta: Mapping[str, Any] | None
    actionable_candidates: Sequence[Any]
    pool: Mapping[str, Any]


class _AsyncTaskProtocol(Protocol):
    """Minimum queued-task projection consumed by task tracking."""

    id: str


def _json_object(value: Any) -> dict[str, Any]:
    """Normalize one dynamic JSON object at the registered-provider boundary."""

    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def refresh_pulse_snapshot(*, target_date: date) -> Any:
    """Refresh the latest pulse snapshot through the owning pulse use case."""

    return _refresh_pulse_snapshot(target_date=target_date)


def fetch_latest_prices(asset_codes: list[str]) -> list[dict[str, Any]]:
    """Fetch latest realtime prices through the owning realtime use case."""

    rows = _fetch_latest_prices(asset_codes)
    if not isinstance(rows, list):
        return []
    return [_json_object(row) for row in rows if isinstance(row, Mapping)]


def load_alpha_homepage_data(
    *, user: Any, top_n: int, portfolio_id: int, pool_mode: str
) -> _AlphaHomepageDataProtocol:
    """Load dashboard alpha homepage data through the owning dashboard module."""

    return cast(
        _AlphaHomepageDataProtocol,
        _load_alpha_homepage_data(
            user=user,
            top_n=top_n,
            portfolio_id=portfolio_id,
            pool_mode=pool_mode,
        ),
    )


def resolve_portfolio_alpha_scope(
    *,
    user_id: int,
    portfolio_id: int | None,
    trade_date: date,
    pool_mode: str | None = None,
) -> _AlphaScopeResolutionProtocol:
    """Resolve the portfolio-scoped alpha universe through the owning alpha module."""

    return cast(
        _AlphaScopeResolutionProtocol,
        _resolve_portfolio_alpha_scope(
            user_id=user_id,
            portfolio_id=portfolio_id,
            trade_date=trade_date,
            pool_mode=pool_mode,
        ),
    )


def queue_alpha_score_prediction(
    *, universe_id: str, trade_date: date, scope_payload: dict[str, Any]
) -> _AsyncTaskProtocol:
    """Queue scoped alpha score prediction through the owning alpha task."""

    return cast(
        _AsyncTaskProtocol,
        _queue_alpha_score_prediction(
            universe_id=universe_id,
            trade_date=trade_date,
            scope_payload=scope_payload,
        ),
    )


def run_alpha_score_prediction_now(
    *,
    universe_id: str,
    trade_date: date,
    scope_payload: dict[str, Any],
) -> Any:
    """Run scoped alpha score prediction synchronously through the owning alpha task."""

    return _run_alpha_score_prediction_now(
        universe_id=universe_id,
        trade_date=trade_date,
        scope_payload=scope_payload,
    )


def _make_provider_repo() -> ProviderConfigRepository:
    return ProviderConfigRepository()


def _get_provider_registry() -> ProviderRegistryProtocol:
    return get_provider_registry()


def _make_raw_audit_repo() -> RawAuditRepository:
    return RawAuditRepository()


def _make_indicator_catalog_repo() -> IndicatorCatalogRepository:
    return IndicatorCatalogRepository()


def _make_publisher_catalog_repo() -> PublisherCatalogRepository:
    return PublisherCatalogRepository()


def _make_indicator_unit_rule_repo() -> IndicatorUnitRuleRepository:
    return IndicatorUnitRuleRepository()


def _make_macro_governance_repo() -> MacroGovernanceRepository:
    return MacroGovernanceRepository()


def make_manage_provider_config_use_case() -> ManageProviderConfigUseCase:
    """Build the provider configuration management use case."""

    return ManageProviderConfigUseCase(_make_provider_repo())


def make_manage_indicator_catalog_use_case() -> ManageIndicatorCatalogUseCase:
    """Build the indicator catalog management use case."""

    return ManageIndicatorCatalogUseCase(
        _make_indicator_catalog_repo(),
        _make_indicator_unit_rule_repo(),
    )


def make_manage_publisher_catalog_use_case() -> ManagePublisherCatalogUseCase:
    """Build the publisher catalog management use case."""

    return ManagePublisherCatalogUseCase(_make_publisher_catalog_repo())


def make_manage_indicator_unit_rule_use_case() -> ManageIndicatorUnitRuleUseCase:
    """Build the indicator unit-rule management use case."""

    return ManageIndicatorUnitRuleUseCase(
        _make_indicator_catalog_repo(),
        _make_indicator_unit_rule_repo(),
    )


def load_macro_governance_payload() -> dict[str, Any]:
    """Build the macro governance audit payload for the admin console."""

    snapshot = _make_macro_governance_repo().build_snapshot()
    indicator_rows = list(snapshot["indicator_rows"])
    missing_sync_candidates = [
        item for item in indicator_rows if "missing_supported" in item["tags"]
    ]
    catalog_only_gaps = [item for item in indicator_rows if "catalog_only_gap" in item["tags"]]
    alias_catalogs = [item for item in indicator_rows if "alias_catalog" in item["tags"]]
    paired_gaps = [item for item in indicator_rows if "paired_gap" in item["tags"]]
    return {
        **snapshot,
        "governed_indicator_codes": list(snapshot["governed_indicator_codes"]),
        "missing_sync_candidates": missing_sync_candidates,
        "catalog_only_gaps": catalog_only_gaps,
        "alias_catalogs": alias_catalogs,
        "paired_gaps": paired_gaps,
    }


def make_run_macro_governance_action_use_case() -> RunMacroGovernanceActionUseCase:
    """Build the macro governance repair use case."""

    return RunMacroGovernanceActionUseCase(
        governance_repo=_make_macro_governance_repo(),
        provider_repo=_make_provider_repo(),
        sync_macro_runner=make_sync_macro_use_case().execute,
    )


def run_macro_governance_action(action: str) -> dict[str, Any]:
    """Execute one governance repair action and return a UI-friendly result."""

    return _json_object(make_run_macro_governance_action_use_case().execute(action))


def make_run_provider_connection_test_use_case() -> RunProviderConnectionTestUseCase:
    """Build the provider connection test use case."""

    class _Tester:
        def test(self, config: ProviderConfig) -> ConnectionTestResult:
            result = run_data_center_connection_test(config)
            if not isinstance(result, ConnectionTestResult):
                raise TypeError("Connection tester returned an invalid result")
            return result

    return RunProviderConnectionTestUseCase(_make_provider_repo(), _Tester())


def load_provider_settings_payload() -> dict[str, Any]:
    """Return the global provider settings as a response payload."""

    settings = DataProviderSettingsRepository().load()
    return {
        "default_source": settings.default_source,
        "enable_failover": settings.enable_failover,
        "failover_tolerance": settings.failover_tolerance,
    }


def get_decision_provider_capability_health_payload() -> dict[str, Any]:
    """Return strict persisted health for providers required by core stock facts."""

    required_capabilities = ("historical_price", "valuation", "financial")
    providers = [provider for provider in _make_provider_repo().list_all() if provider.is_active]
    capabilities: dict[str, Any] = {}
    blocked_capabilities: list[str] = []
    for capability in required_capabilities:
        candidates: list[dict[str, Any]] = []
        for provider in providers:
            supported = SOURCE_TYPE_CAPABILITIES.get(provider.source_type, ())
            if capability not in set(supported):
                continue
            metric = dict((provider.extra_config.get("health_metrics") or {}).get(capability) or {})
            candidates.append(
                build_capability_health_payload(
                    {
                        "provider_name": provider.name,
                        "capability": capability,
                        "status": metric.get("last_status", "unknown"),
                        "consecutive_failures": metric.get("consecutive_failures", 0),
                        "last_success_at": metric.get("last_success_at"),
                        "avg_latency_ms": metric.get("avg_latency_ms"),
                    },
                    provider.extra_config,
                )
            )
        healthy = any(not item["must_not_use_for_decision"] for item in candidates)
        capabilities[capability] = {
            "status": "ok" if healthy else "blocked",
            "providers": candidates,
            "must_not_use_for_decision": not healthy,
        }
        if not healthy:
            blocked_capabilities.append(capability)
    return {
        "status": "ok" if not blocked_capabilities else "blocked",
        "capabilities": capabilities,
        "blocked_capabilities": blocked_capabilities,
        "must_not_use_for_decision": bool(blocked_capabilities),
        "block_reason_code": (
            "" if not blocked_capabilities else "decision_provider_capabilities_unhealthy"
        ),
    }


def can_create_provider_settings() -> bool:
    """Return whether the singleton provider-settings row can be created."""

    return not DataProviderSettingsRepository().has_settings()


def save_provider_settings_payload(
    *,
    default_source: str,
    enable_failover: bool,
    failover_tolerance: float,
) -> dict[str, Any]:
    """Persist the global provider settings and return a response payload."""

    saved = DataProviderSettingsRepository().save(
        DataProviderSettings(
            default_source=default_source,
            enable_failover=enable_failover,
            failover_tolerance=failover_tolerance,
        )
    )
    return {
        "default_source": saved.default_source,
        "enable_failover": saved.enable_failover,
        "failover_tolerance": saved.failover_tolerance,
    }


def load_production_coverage_universe_config_payload() -> dict[str, Any]:
    """Return production coverage universe settings as a response payload."""

    return _json_object(ProductionCoverageUniverseConfigRepository().load().to_dict())


def save_production_coverage_universe_config_payload(
    *,
    universe_id: str,
    asset_type: str,
    exchanges: list[str],
    include_inactive: bool,
    min_active_asset_count: int,
    min_star_market_count: int,
    min_chinext_count: int,
    min_bse_count: int,
    description: str,
) -> dict[str, Any]:
    """Persist production coverage universe settings and return the saved payload."""

    config = ProductionCoverageUniverseConfig(
        universe_id=universe_id,
        asset_type=asset_type,
        exchanges=exchanges,
        include_inactive=include_inactive,
        min_active_asset_count=min_active_asset_count,
        min_star_market_count=min_star_market_count,
        min_chinext_count=min_chinext_count,
        min_bse_count=min_bse_count,
        description=description,
    )
    return _json_object(ProductionCoverageUniverseConfigRepository().save(config).to_dict())


def make_resolve_asset_use_case() -> ResolveAssetUseCase:
    """Build the asset resolution use case."""

    return ResolveAssetUseCase(AssetRepository())


def make_query_macro_series_use_case() -> QueryMacroSeriesUseCase:
    """Build the macro series query use case."""

    return QueryMacroSeriesUseCase(
        MacroFactRepository(),
        _make_indicator_catalog_repo(),
        _make_indicator_unit_rule_repo(),
        _make_publisher_catalog_repo(),
    )


def make_query_price_history_use_case() -> QueryPriceHistoryUseCase:
    """Build the historical price query use case."""

    return QueryPriceHistoryUseCase(PriceBarRepository())


def make_query_latest_quote_use_case() -> QueryLatestQuoteUseCase:
    """Build the latest quote query use case."""

    return QueryLatestQuoteUseCase(QuoteSnapshotRepository())


def fetch_latest_realtime_prices(asset_codes: list[str]) -> list[dict[str, Any]]:
    """Fetch real-time prices from the realtime app fallback service."""

    return fetch_latest_prices(asset_codes)


def make_query_fund_nav_use_case() -> QueryFundNavUseCase:
    """Build the fund NAV query use case."""

    return QueryFundNavUseCase(FundNavRepository())


def make_query_financials_use_case() -> QueryFinancialsUseCase:
    """Build the financial facts query use case."""

    return QueryFinancialsUseCase(FinancialFactRepository())


def make_query_valuations_use_case() -> QueryValuationsUseCase:
    """Build the valuation query use case."""

    return QueryValuationsUseCase(ValuationFactRepository())


def make_query_sector_constituents_use_case() -> QuerySectorConstituentsUseCase:
    """Build the sector constituents query use case."""

    return QuerySectorConstituentsUseCase(SectorMembershipRepository())


def make_query_news_use_case() -> QueryNewsUseCase:
    """Build the news query use case."""

    return QueryNewsUseCase(NewsRepository())


def make_query_capital_flows_use_case() -> QueryCapitalFlowsUseCase:
    """Build the capital flow query use case."""

    return QueryCapitalFlowsUseCase(CapitalFlowRepository())


def make_manage_market_thermometer_config_use_case() -> ManageMarketThermometerConfigUseCase:
    """Build the market-thermometer config use case."""

    return ManageMarketThermometerConfigUseCase(MarketThermometerConfigRepository())


def make_manage_market_thermometer_user_override_use_case() -> (
    ManageMarketThermometerUserOverrideUseCase
):
    """Build the market-thermometer user override use case."""

    return ManageMarketThermometerUserOverrideUseCase(MarketThermometerUserOverrideRepository())


def make_calculate_market_thermometer_use_case() -> CalculateMarketThermometerUseCase:
    """Build the market-thermometer calculation use case."""

    return CalculateMarketThermometerUseCase(
        config_repo=MarketThermometerConfigRepository(),
        snapshot_repo=MarketThermometerSnapshotRepository(),
        override_repo=MarketThermometerUserOverrideRepository(),
        macro_repo=MacroFactRepository(),
    )


def make_sync_market_thermometer_inputs_use_case() -> SyncMarketThermometerInputsUseCase:
    """Build the market-thermometer input sync use case."""

    from .macro_fact_governance import MacroFactGovernanceNormalizer

    catalog_repo = IndicatorCatalogRepository()
    unit_rule_repo = IndicatorUnitRuleRepository()
    return SyncMarketThermometerInputsUseCase(
        provider_repo=ProviderConfigRepository(),
        provider_registry=get_provider_registry(),
        macro_repo=MacroFactRepository(),
        news_repo=NewsRepository(),
        raw_audit_repo=RawAuditRepository(),
        macro_normalizer=MacroFactGovernanceNormalizer(catalog_repo, unit_rule_repo),
    )


def make_import_investor_accounts_use_case() -> ImportInvestorAccountsUseCase:
    """Build the investor-account import use case."""

    from .macro_fact_governance import MacroFactGovernanceNormalizer

    return ImportInvestorAccountsUseCase(
        MacroFactRepository(),
        MacroFactGovernanceNormalizer(
            IndicatorCatalogRepository(),
            IndicatorUnitRuleRepository(),
        ),
    )


def load_market_thermometer_payload(
    *,
    user_id: int | None = None,
    use_personal_thresholds: bool = True,
) -> dict[str, Any]:
    """Return the latest market-thermometer payload for UI/API consumers."""

    return _json_object(
        make_calculate_market_thermometer_use_case().build_current_payload(
            user_id=user_id,
            use_personal_thresholds=use_personal_thresholds,
        )
    )


def load_market_thermometer_override_payload(*, user_id: int) -> dict[str, Any]:
    """Return effective and override thresholds for one user."""

    config = MarketThermometerConfigRepository().load()
    override = MarketThermometerUserOverrideRepository().get_by_user_id(user_id)
    return _json_object(build_market_thermometer_override_payload(config=config, override=override))


def _build_pulse_refresher() -> Callable[[date], Any]:
    def _refresh(target_date: date) -> Any:
        return refresh_pulse_snapshot(target_date=target_date)

    return _refresh


def _build_alpha_refresher(
    user: Any,
) -> Callable[[date, int | None], dict[str, Any]]:
    def _refresh(target_date: date, portfolio_id: int | None) -> dict[str, Any]:
        if portfolio_id is None:
            return {"status": "skipped", "message": "portfolio_id is required"}

        from django.core.management import CommandError, call_command

        try:
            call_command(
                "build_qlib_data",
                check_only=True,
                target_date=target_date.isoformat(),
                verbosity=0,
            )
        except CommandError:
            call_command(
                "build_qlib_data",
                target_date=target_date.isoformat(),
                universes="csi300,csi500,sse50,csi1000",
                lookback_days=400,
                verbosity=0,
            )
        resolved = resolve_portfolio_alpha_scope(
            user_id=user.id,
            portfolio_id=portfolio_id,
            trade_date=target_date,
        )
        quote_sync_result = _sync_scope_quotes(
            list(getattr(resolved.scope, "instrument_codes", ()) or ())
        )
        kombu_exceptions = importlib.import_module("kombu.exceptions")
        KombuOperationalError = cast(
            type[Exception],
            kombu_exceptions.OperationalError,
        )

        try:
            task = queue_alpha_score_prediction(
                universe_id=resolved.scope.universe_id,
                trade_date=target_date,
                scope_payload=resolved.scope.to_dict(),
            )
            record_pending_task(
                task_id=task.id,
                task_name="apps.alpha.application.tasks.qlib_predict_scores",
                args=(resolved.scope.universe_id, target_date.isoformat(), 30),
                kwargs={"scope_payload": resolved.scope.to_dict()},
            )
        except (KombuOperationalError, ConnectionError, OSError, TimeoutError) as exc:
            return {
                "status": "queue_failed",
                "scope_hash": resolved.scope.scope_hash,
                "universe_id": resolved.scope.universe_id,
                "task_id": "",
                "qlib_result": {
                    "message": "Scoped Alpha inference queue is unavailable.",
                    "error_message": str(exc),
                },
                "quote_sync": quote_sync_result,
            }
        return {
            "status": "queued",
            "scope_hash": resolved.scope.scope_hash,
            "universe_id": resolved.scope.universe_id,
            "task_id": getattr(task, "id", ""),
            "qlib_result": {
                "message": "Scoped Alpha inference queued.",
                "task_id": getattr(task, "id", ""),
            },
            "quote_sync": quote_sync_result,
        }

    return _refresh


def _sync_scope_quotes(asset_codes: list[str]) -> dict[str, Any]:
    normalized_codes = [str(code or "").strip().upper() for code in asset_codes if code]
    if not normalized_codes:
        return {"status": "skipped", "message": "No scoped instruments to sync."}

    provider_repo = _make_provider_repo()
    source_priority = {"akshare": 0, "eastmoney": 1, "tencent": 2, "tushare": 3}
    providers = [
        item
        for item in provider_repo.list_all()
        if item.is_active and item.id is not None and item.source_type in source_priority
    ]
    providers.sort(key=lambda item: (source_priority[item.source_type], item.priority))
    provider = providers[0] if providers else None
    if provider is None or provider.id is None:
        return {"status": "skipped", "message": "No realtime quote provider is available."}

    try:
        result = SyncQuoteUseCase(
            provider_repo=provider_repo,
            provider_registry=build_provider_registry_for_repo(provider_repo),
            fact_repo=QuoteSnapshotRepository(),
            raw_audit_repo=RawAuditRepository(),
        ).execute(
            SyncQuoteRequest(
                provider_id=provider.id,
                asset_codes=normalized_codes,
            )
        )
    except Exception as exc:
        return {"status": "failed", "error_message": str(exc)}
    return _json_object(result.to_dict())


def refresh_decision_quote_snapshots(
    *,
    asset_codes: list[str] | None = None,
    quote_max_age_hours: float | None = None,
) -> dict[str, Any]:
    """Sync decision-grade quote snapshots and return a readiness payload."""

    max_age_hours = float(quote_max_age_hours if quote_max_age_hours is not None else 4.0)
    requested_codes = asset_codes or list(DEFAULT_DECISION_ASSET_CODES)
    normalized_codes = []
    seen_codes = set()
    for code in requested_codes:
        normalized = str(code or "").strip().upper()
        if normalized and normalized not in seen_codes:
            normalized_codes.append(normalized)
            seen_codes.add(normalized)

    sync_payload = _sync_scope_quotes(normalized_codes)
    readiness = get_decision_data_readiness_payload(
        asset_codes=normalized_codes,
        quote_max_age_hours=max_age_hours,
    )
    failed_codes = [
        code
        for code, detail in readiness.get("quotes", {}).items()
        if detail.get("must_not_use_for_decision") or detail.get("status") == "blocked"
    ]
    return {
        "status": (
            "blocked"
            if readiness.get("must_not_use_for_decision")
            else sync_payload.get("status", "success")
        ),
        "asset_codes": normalized_codes,
        "synced_count": int(sync_payload.get("stored_count") or 0),
        "failed_codes": failed_codes,
        "must_not_use_for_decision": bool(readiness.get("must_not_use_for_decision")),
        "blocked_reasons": list(readiness.get("blocked_reasons") or []),
        "sync": sync_payload,
        "readiness": readiness,
    }


def get_decision_data_readiness_payload(
    *,
    asset_codes: list[str] | None = None,
    quote_max_age_hours: float | None = None,
) -> dict[str, Any]:
    """Return quote and market thermometer readiness for decision use."""

    max_age_hours = float(quote_max_age_hours if quote_max_age_hours is not None else 4.0)
    requested_codes = asset_codes or list(DEFAULT_DECISION_ASSET_CODES)
    normalized_codes = []
    seen_codes = set()
    for code in requested_codes:
        normalized = str(code or "").strip().upper()
        if normalized and normalized not in seen_codes:
            normalized_codes.append(normalized)
            seen_codes.add(normalized)

    quote_query = QueryLatestQuoteUseCase(QuoteSnapshotRepository())
    quotes: dict[str, Any] = {}
    blocked_reasons: list[str] = []
    for asset_code in normalized_codes:
        quote = quote_query.execute(
            LatestQuoteRequest(asset_code=asset_code, max_age_hours=max_age_hours)
        )
        if quote is None:
            reason = f"{asset_code}: 无可用最新行情。"
            quotes[asset_code] = {
                "status": "blocked",
                "asset_code": asset_code,
                "must_not_use_for_decision": True,
                "blocked_reason": reason,
                "max_age_hours": max_age_hours,
            }
            blocked_reasons.append(reason)
            continue

        quote_payload = quote.to_dict()
        quote_payload["status"] = "blocked" if quote.must_not_use_for_decision else "ok"
        quotes[asset_code] = quote_payload
        if quote.must_not_use_for_decision:
            blocked_reasons.append(
                f"{asset_code}: {quote.blocked_reason or quote.freshness_status}"
            )

    thermometer_payload = make_calculate_market_thermometer_use_case().build_current_payload(
        auto_calculate=False,
    )
    skipped_thermometer_payload = _build_skipped_latest_market_thermometer_payload(
        thermometer_payload=thermometer_payload,
    )

    if not thermometer_payload.get("observed_at"):
        reason = "无可用市场温度计快照。"
        thermometer_payload = {
            "status": "blocked",
            "must_not_use_for_decision": True,
            "blocked_reason": reason,
        }
        blocked_reasons.append(reason)
    else:
        thermometer_payload["status"] = (
            "blocked" if thermometer_payload.get("must_not_use_for_decision") else "ok"
        )
        if thermometer_payload.get("must_not_use_for_decision"):
            blocked_reasons.append("市场温度计标记为 must_not_use_for_decision。")

    payload = {
        "status": "blocked" if blocked_reasons else "ok",
        "asset_codes": normalized_codes,
        "quote_max_age_hours": max_age_hours,
        "quotes": quotes,
        "market_thermometer": thermometer_payload,
        "must_not_use_for_decision": bool(blocked_reasons),
        "blocked_reasons": blocked_reasons,
    }
    if skipped_thermometer_payload is not None:
        payload["skipped_latest_market_thermometer"] = skipped_thermometer_payload
    return payload


def _build_skipped_latest_market_thermometer_payload(
    *,
    thermometer_payload: dict[str, Any],
) -> dict[str, Any] | None:
    latest = MarketThermometerSnapshotRepository().get_latest()
    if latest is None:
        return None

    payload_observed_at = str(thermometer_payload.get("observed_at") or "")
    latest_observed_at = latest.observed_at.isoformat()
    latest_is_skipped = latest_observed_at != payload_observed_at
    latest_is_blocked = latest.must_not_use_for_decision
    if not latest_is_skipped and not latest_is_blocked:
        return None

    skipped_payload = latest.to_dict()
    skipped_payload["status"] = "blocked" if latest_is_blocked else "skipped"
    if latest_is_skipped:
        skipped_payload["skip_reason"] = "latest_snapshot_after_decision_safe_date"
    elif latest_is_blocked:
        skipped_payload["skip_reason"] = "latest_snapshot_must_not_use_for_decision"
    return _json_object(skipped_payload)


def _build_alpha_status_reader(
    user: Any,
) -> Callable[[date, int | None], dict[str, Any]]:
    def _read(target_date: date, portfolio_id: int | None) -> dict[str, Any]:
        if portfolio_id is None:
            return {"status": "blocked", "recommendation_ready": False}

        data = load_alpha_homepage_data(
            user=user,
            top_n=10,
            portfolio_id=portfolio_id,
            pool_mode="price_covered",
        )
        meta = dict(data.meta or {})
        return {
            "status": "ready" if meta.get("recommendation_ready") else "blocked",
            "recommendation_ready": bool(meta.get("recommendation_ready")),
            "actionable_candidate_count": len(data.actionable_candidates),
            "requested_trade_date": meta.get("requested_trade_date") or target_date.isoformat(),
            "verified_asof_date": meta.get("verified_asof_date"),
            "scope_verification_status": meta.get("scope_verification_status"),
            "scope_hash": meta.get("scope_hash") or data.pool.get("scope_hash"),
            "freshness_status": meta.get("freshness_status"),
            "latest_completed_session_result": bool(
                meta.get("latest_completed_session_result", False)
            ),
            "must_not_use_for_decision": bool(meta.get("must_not_use_for_decision", True)),
            "blocked_reason": meta.get("blocked_reason")
            or meta.get("no_recommendation_reason", ""),
        }

    return _read


def make_decision_repair_use_case(
    user: Any,
) -> RepairDecisionDataReliabilityUseCase:
    """Build the decision reliability repair use case."""

    return RepairDecisionDataReliabilityUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        macro_fact_repo=MacroFactRepository(),
        indicator_catalog_repo=_make_indicator_catalog_repo(),
        indicator_unit_rule_repo=_make_indicator_unit_rule_repo(),
        price_bar_repo=PriceBarRepository(),
        quote_snapshot_repo=QuoteSnapshotRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
        pulse_refresher=_build_pulse_refresher(),
        alpha_refresher=_build_alpha_refresher(user),
        alpha_status_reader=_build_alpha_status_reader(user),
    )


def make_sync_macro_use_case() -> SyncMacroUseCase:
    """Build the macro sync use case."""

    return SyncMacroUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=MacroFactRepository(),
        catalog_repo=_make_indicator_catalog_repo(),
        unit_rule_repo=_make_indicator_unit_rule_repo(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_macro_batch_use_case() -> SyncMacroBatchUseCase:
    """Build the canonical provider-selected macro batch sync use case."""

    provider_repo = _make_provider_repo()
    provider_registry = _get_provider_registry()
    sync_use_case = SyncMacroUseCase(
        provider_repo=provider_repo,
        provider_registry=provider_registry,
        fact_repo=MacroFactRepository(),
        catalog_repo=_make_indicator_catalog_repo(),
        unit_rule_repo=_make_indicator_unit_rule_repo(),
        raw_audit_repo=_make_raw_audit_repo(),
    )
    return SyncMacroBatchUseCase(
        provider_repo=provider_repo,
        provider_registry=provider_registry,
        sync_use_case=sync_use_case,
    )


def make_sync_price_use_case() -> SyncPriceUseCase:
    """Build the historical price sync use case."""

    return SyncPriceUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=PriceBarRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_quote_use_case() -> SyncQuoteUseCase:
    """Build the quote sync use case."""

    return SyncQuoteUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=QuoteSnapshotRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def purge_all_quote_snapshots_for_rebuild() -> int:
    """Delete all quote snapshots for a separately backed-up rebuild workflow."""

    return QuoteSnapshotRepository().delete_all()


def make_sync_fund_nav_use_case() -> SyncFundNavUseCase:
    """Build the fund NAV sync use case."""

    return SyncFundNavUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=FundNavRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_financial_use_case() -> SyncFinancialUseCase:
    """Build the financial facts sync use case."""

    return SyncFinancialUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=FinancialFactRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def get_active_provider_selection_by_source(
    source_type: str,
) -> tuple[int, str] | None:
    """Return the highest-priority active provider id and configured name."""

    providers = _make_provider_repo().get_active_by_type(source_type)
    if not providers:
        return None
    provider = providers[0]
    if provider.id is None or not provider.name.strip():
        return None
    return int(provider.id), provider.name.strip()


def get_active_provider_id_by_source(source_type: str) -> int | None:
    """Return the highest-priority active provider id for a source type."""

    selection = get_active_provider_selection_by_source(source_type)
    return selection[0] if selection is not None else None


def make_sync_valuation_use_case() -> SyncValuationUseCase:
    """Build the valuation sync use case."""

    return SyncValuationUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=ValuationFactRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_sector_membership_use_case() -> SyncSectorMembershipUseCase:
    """Build the sector membership sync use case."""

    return SyncSectorMembershipUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=SectorMembershipRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_on_demand_data_center_service() -> OnDemandDataCenterService:
    """Build the single-asset read-through Data Center service."""

    return OnDemandDataCenterService(
        price_repo=PriceBarRepository(),
        valuation_repo=ValuationFactRepository(),
        financial_repo=FinancialFactRepository(),
        quote_repo=QuoteSnapshotRepository(),
        sync_price_use_case=make_sync_price_use_case(),
        sync_valuation_use_case=make_sync_valuation_use_case(),
        sync_financial_use_case=make_sync_financial_use_case(),
        sync_quote_use_case=make_sync_quote_use_case(),
        provider_id_resolver=get_active_provider_id_by_source,
    )


def make_sync_news_use_case() -> SyncNewsUseCase:
    """Build the news sync use case."""

    return SyncNewsUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=NewsRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def sync_market_news_for_sentiment(*, limit: int = 100) -> SyncResult:
    """Refresh broad-market news through the configured NEWS capability.

    Provider choice remains database-driven. Recoverable failures advance to
    the next active NEWS-capable provider; an empty but successful response is
    retained as a diagnostic fallback because it may only mean that all fetched
    articles were already persisted.
    """

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit must be an integer between 1 and 200")

    from apps.data_center.application.sync_use_cases import (
        RECOVERABLE_DATA_CENTER_EXCEPTIONS,
    )

    providers = sorted(_make_provider_repo().list_active(), key=lambda item: item.priority)
    candidates = [
        provider
        for provider in providers
        if provider.id is not None
        and DataCapability.NEWS.value in SOURCE_TYPE_CAPABILITIES.get(provider.source_type, ())
    ]
    if not candidates:
        raise DataFetchError("No active data-center provider supports market news")

    sync_use_case = make_sync_news_use_case()
    empty_success: SyncResult | None = None
    failures: list[str] = []
    for provider in candidates:
        provider_id = provider.id
        if provider_id is None:
            continue
        try:
            result = sync_use_case.execute(
                SyncNewsRequest(
                    provider_id=provider_id,
                    asset_code="",
                    limit=limit,
                )
            )
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            failures.append(f"{provider.name}:{type(exc).__name__}")
            continue
        if result.stored_count > 0:
            if failures or empty_success is not None:
                reasons = [*failures]
                if empty_success is not None:
                    reasons.append(f"{empty_success.provider_name}:empty_result")
                return SyncResult(
                    domain=result.domain,
                    provider_name=result.provider_name,
                    stored_count=result.stored_count,
                    status="partial",
                    error_message="fallback_used_after_" + ",".join(reasons),
                )
            return result
        if empty_success is None:
            empty_success = result

    if empty_success is not None:
        return empty_success
    failure_summary = ", ".join(failures) or "no provider completed"
    raise DataFetchError(f"Market news synchronization failed ({failure_summary})")


def make_sync_capital_flow_use_case() -> SyncCapitalFlowUseCase:
    """Build the capital flow sync use case."""

    return SyncCapitalFlowUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=CapitalFlowRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )
