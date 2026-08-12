"""Application-side dependency builders for data_center interface endpoints."""

from __future__ import annotations

import importlib
import math
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from functools import wraps
from typing import Any, ParamSpec, Protocol, TypeVar, cast

from apps.data_center.application.provider_capabilities import SOURCE_TYPE_CAPABILITIES
from apps.data_center.application.provider_health import build_capability_health_payload
from apps.data_center.composition import (
    AssetRepository,
    CapitalFlowRepository,
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
from apps.data_center.domain.protocols import (
    MacroFactRepositoryProtocol,
    ProviderRegistryProtocol,
)
from core.integration.config_center_runtime import (
    activate_runtime_profile_patch,
    get_active_runtime_value,
)
from core.integration.runtime_imports import record_pending_task

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
    ResolveAssetUseCase,
    RunMacroGovernanceActionUseCase,
    SyncQuoteUseCase,
)


def _make_macro_fact_repository() -> MacroFactRepositoryProtocol:
    """Adapt the concrete PIT-aware repository to the application port."""

    return cast(MacroFactRepositoryProtocol, MacroFactRepository())


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


def _build_alpha_refresher(
    user: Any,
) -> Callable[[date, int | None], dict[str, Any]]:
    """Build the whitelisted Qlib command orchestration entrypoint."""

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
    """Return complete typed provider settings or an explicit blocked payload."""

    module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    environment = "production" if module.endswith(".production") else "development"
    try:
        default_source = get_active_runtime_value(
            environment=environment,
            definition_key="data_center.provider.default_source",
        )
        if default_source is None:
            raise RuntimeError("provider_runtime_default_source_missing")
        if (
            not isinstance(default_source, str)
            or default_source not in DataProviderSettings.SOURCE_CHOICES
        ):
            raise RuntimeError("provider_runtime_default_source_invalid")

        enable_failover = get_active_runtime_value(
            environment=environment,
            definition_key="data_center.provider.enable_failover",
        )
        if enable_failover is None:
            raise RuntimeError("provider_runtime_failover_enabled_missing")
        if not isinstance(enable_failover, bool):
            raise RuntimeError("provider_runtime_failover_enabled_invalid")

        runtime_tolerance = get_active_runtime_value(
            environment=environment,
            definition_key="data_center.provider.failover_tolerance",
        )
        if runtime_tolerance is None:
            raise RuntimeError("provider_runtime_failover_tolerance_missing")
        if isinstance(runtime_tolerance, bool) or not isinstance(runtime_tolerance, (int, float)):
            raise RuntimeError("provider_runtime_failover_tolerance_invalid")
        failover_tolerance = float(runtime_tolerance)
        if not math.isfinite(failover_tolerance) or not 0.0 <= failover_tolerance <= 1.0:
            raise RuntimeError("provider_runtime_failover_tolerance_invalid")
    except RuntimeError as exc:
        return {
            "default_source": None,
            "enable_failover": None,
            "failover_tolerance": None,
            "status": "blocked",
            "source": "config_center_runtime_profile",
            "must_not_use_for_decision": True,
            "blocked_reason": str(exc) or "provider_runtime_config_unavailable",
        }
    except Exception:
        return {
            "default_source": None,
            "enable_failover": None,
            "failover_tolerance": None,
            "status": "blocked",
            "source": "config_center_runtime_profile",
            "must_not_use_for_decision": True,
            "blocked_reason": "provider_runtime_snapshot_unavailable",
        }
    return {
        "default_source": default_source,
        "enable_failover": enable_failover,
        "failover_tolerance": failover_tolerance,
        "status": "active",
        "source": "config_center_runtime_profile",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
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
            dataset_key = DataCapability(capability).dataset_key
            dataset_metrics = provider.extra_config.get("health_metrics_by_dataset") or {}
            metric = dict(
                (dataset_metrics.get(dataset_key) if isinstance(dataset_metrics, dict) else None)
                or (provider.extra_config.get("health_metrics") or {}).get(capability)
                or {}
            )
            candidates.append(
                build_capability_health_payload(
                    {
                        "provider_name": provider.name,
                        "capability": capability,
                        "dataset_key": dataset_key,
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


def save_provider_settings_payload(
    *,
    default_source: str,
    enable_failover: bool,
    failover_tolerance: float,
    actor: str = "data-center-admin",
) -> dict[str, Any]:
    """Persist provider source metadata and typed failover runtime values."""

    module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    environment = "production" if module.endswith(".production") else "development"
    runtime_patch = {
        "data_center.provider.default_source": str(default_source),
        "data_center.provider.enable_failover": bool(enable_failover),
        "data_center.provider.failover_tolerance": float(failover_tolerance),
    }
    activate_runtime_profile_patch(
        environment=environment,
        patch=runtime_patch,
        bootstrap_values=runtime_patch,
        actor=str(actor or "data-center-admin"),
        reason="Data Center provider runtime settings updated",
    )
    return load_provider_settings_payload()


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
        _make_macro_fact_repository(),
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
        macro_repo=_make_macro_fact_repository(),
    )


def make_sync_market_thermometer_inputs_use_case() -> SyncMarketThermometerInputsUseCase:
    """Build the market-thermometer input sync use case."""

    from .macro_fact_governance import MacroFactGovernanceNormalizer

    catalog_repo = IndicatorCatalogRepository()
    unit_rule_repo = IndicatorUnitRuleRepository()
    return SyncMarketThermometerInputsUseCase(
        provider_repo=ProviderConfigRepository(),
        provider_registry=get_provider_registry(),
        macro_repo=_make_macro_fact_repository(),
        news_repo=NewsRepository(),
        raw_audit_repo=RawAuditRepository(),
        macro_normalizer=MacroFactGovernanceNormalizer(catalog_repo, unit_rule_repo),
    )


def make_import_investor_accounts_use_case() -> ImportInvestorAccountsUseCase:
    """Build the investor-account import use case."""

    from .macro_fact_governance import MacroFactGovernanceNormalizer

    return ImportInvestorAccountsUseCase(
        _make_macro_fact_repository(),
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


from . import interface_services_decision_sync as _decision_sync  # noqa: E402

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _sync_decision_dependencies(target_name: str) -> None:
    """Keep monkeypatch-compatible facade dependencies visible to split services."""

    split_globals = vars(_decision_sync)
    for name, value in tuple(globals().items()):
        if name == target_name or name not in split_globals:
            continue
        if getattr(value, "_decision_sync_target", None) is not None:
            continue
        setattr(_decision_sync, name, value)


def _bind_decision_sync(
    target_name: str,
    target: Callable[_P, _R],
) -> Callable[_P, _R]:
    """Bind one split implementation while preserving the legacy patch surface."""

    @wraps(target)
    def _bound(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        _sync_decision_dependencies(target_name)
        return target(*args, **kwargs)

    setattr(_bound, "_decision_sync_target", target_name)  # noqa: B010
    return _bound


refresh_decision_quote_snapshots = _bind_decision_sync(
    "refresh_decision_quote_snapshots", _decision_sync.refresh_decision_quote_snapshots
)
get_decision_data_readiness_payload = _bind_decision_sync(
    "get_decision_data_readiness_payload", _decision_sync.get_decision_data_readiness_payload
)
make_decision_repair_use_case = _bind_decision_sync(
    "make_decision_repair_use_case", _decision_sync.make_decision_repair_use_case
)
make_sync_macro_use_case = _bind_decision_sync(
    "make_sync_macro_use_case", _decision_sync.make_sync_macro_use_case
)
make_sync_macro_batch_use_case = _bind_decision_sync(
    "make_sync_macro_batch_use_case", _decision_sync.make_sync_macro_batch_use_case
)
make_sync_price_use_case = _bind_decision_sync(
    "make_sync_price_use_case", _decision_sync.make_sync_price_use_case
)
make_sync_quote_use_case = _bind_decision_sync(
    "make_sync_quote_use_case", _decision_sync.make_sync_quote_use_case
)
make_sync_fund_nav_use_case = _bind_decision_sync(
    "make_sync_fund_nav_use_case", _decision_sync.make_sync_fund_nav_use_case
)
make_sync_financial_use_case = _bind_decision_sync(
    "make_sync_financial_use_case", _decision_sync.make_sync_financial_use_case
)
get_active_provider_selection_by_source = _bind_decision_sync(
    "get_active_provider_selection_by_source",
    _decision_sync.get_active_provider_selection_by_source,
)
get_active_provider_id_by_source = _bind_decision_sync(
    "get_active_provider_id_by_source", _decision_sync.get_active_provider_id_by_source
)
make_sync_valuation_use_case = _bind_decision_sync(
    "make_sync_valuation_use_case", _decision_sync.make_sync_valuation_use_case
)
make_sync_current_valuation_batch_use_case = _bind_decision_sync(
    "make_sync_current_valuation_batch_use_case",
    _decision_sync.make_sync_current_valuation_batch_use_case,
)
make_sync_sector_membership_use_case = _bind_decision_sync(
    "make_sync_sector_membership_use_case", _decision_sync.make_sync_sector_membership_use_case
)
make_on_demand_data_center_service = _bind_decision_sync(
    "make_on_demand_data_center_service", _decision_sync.make_on_demand_data_center_service
)
make_sync_news_use_case = _bind_decision_sync(
    "make_sync_news_use_case", _decision_sync.make_sync_news_use_case
)
sync_market_news_for_sentiment = _bind_decision_sync(
    "sync_market_news_for_sentiment", _decision_sync.sync_market_news_for_sentiment
)
make_sync_capital_flow_use_case = _bind_decision_sync(
    "make_sync_capital_flow_use_case", _decision_sync.make_sync_capital_flow_use_case
)
_build_pulse_refresher = _bind_decision_sync(
    "_build_pulse_refresher", _decision_sync._build_pulse_refresher
)
_build_alpha_refresher = _bind_decision_sync("_build_alpha_refresher", _build_alpha_refresher)
_sync_scope_quotes = _bind_decision_sync("_sync_scope_quotes", _decision_sync._sync_scope_quotes)
_build_skipped_latest_market_thermometer_payload = _bind_decision_sync(
    "_build_skipped_latest_market_thermometer_payload",
    _decision_sync._build_skipped_latest_market_thermometer_payload,
)
_build_alpha_status_reader = _bind_decision_sync(
    "_build_alpha_status_reader", _decision_sync._build_alpha_status_reader
)
_COMPATIBILITY_EXPORTS = (build_provider_registry_for_repo, SyncQuoteUseCase)
