"""Application-side dependency builders for data_center interface endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.data_center.application.dtos import SyncQuoteRequest
from apps.data_center.domain.entities import DataProviderSettings
from core.integration.alpha_runtime import (
    queue_alpha_score_prediction,
    resolve_portfolio_alpha_scope,
)
from core.integration.alpha_homepage import load_alpha_homepage_data
from core.integration.pulse_refresh import refresh_pulse_snapshot
from core.integration.realtime_prices import fetch_latest_prices

from .use_cases import (
    ManageProviderConfigUseCase,
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
    RunProviderConnectionTestUseCase,
    SyncCapitalFlowUseCase,
    SyncFinancialUseCase,
    SyncFundNavUseCase,
    SyncMacroUseCase,
    SyncNewsUseCase,
    SyncPriceUseCase,
    SyncQuoteUseCase,
    SyncSectorMembershipUseCase,
    SyncValuationUseCase,
)
from .repository_provider import (
    AssetRepository,
    CapitalFlowRepository,
    DataProviderSettingsRepository,
    FinancialFactRepository,
    FundNavRepository,
    IndicatorCatalogRepository,
    LegacyMacroSeriesRepository,
    MacroFactRepository,
    NewsRepository,
    PriceBarRepository,
    ProviderConfigRepository,
    QuoteSnapshotRepository,
    RawAuditRepository,
    SectorMembershipRepository,
    ValuationFactRepository,
    build_unified_provider_factory,
    run_data_center_connection_test,
)


def _make_provider_repo() -> ProviderConfigRepository:
    return ProviderConfigRepository()


def _make_provider_factory():
    return build_unified_provider_factory()


def _make_raw_audit_repo() -> RawAuditRepository:
    return RawAuditRepository()


def make_manage_provider_config_use_case() -> ManageProviderConfigUseCase:
    """Build the provider configuration management use case."""

    return ManageProviderConfigUseCase(_make_provider_repo())


def make_run_provider_connection_test_use_case() -> RunProviderConnectionTestUseCase:
    """Build the provider connection test use case."""

    class _Tester:
        def test(self, config):
            return run_data_center_connection_test(config)

    return RunProviderConnectionTestUseCase(_make_provider_repo(), _Tester())


def load_provider_settings_payload() -> dict[str, Any]:
    """Return the global provider settings as a response payload."""

    settings = DataProviderSettingsRepository().load()
    return {
        "default_source": settings.default_source,
        "enable_failover": settings.enable_failover,
        "failover_tolerance": settings.failover_tolerance,
    }


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


def make_resolve_asset_use_case() -> ResolveAssetUseCase:
    """Build the asset resolution use case."""

    return ResolveAssetUseCase(AssetRepository())


def make_query_macro_series_use_case() -> QueryMacroSeriesUseCase:
    """Build the macro series query use case."""

    return QueryMacroSeriesUseCase(
        MacroFactRepository(),
        IndicatorCatalogRepository(),
        LegacyMacroSeriesRepository(),
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


def _build_pulse_refresher():
    def _refresh(target_date: date):
        return refresh_pulse_snapshot(target_date=target_date)

    return _refresh


def _build_alpha_refresher(user):
    def _refresh(target_date: date, portfolio_id: int | None) -> dict:
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
        from kombu.exceptions import OperationalError as KombuOperationalError

        try:
            task = queue_alpha_score_prediction(
                universe_id=resolved.scope.universe_id,
                trade_date=target_date,
                scope_payload=resolved.scope.to_dict(),
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
    source_priority = {"akshare": 0, "eastmoney": 1, "tushare": 2}
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
            provider_factory=UnifiedProviderFactory(provider_repo),
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
    return result.to_dict()


def _build_alpha_status_reader(user):
    def _read(target_date: date, portfolio_id: int | None) -> dict:
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


def make_decision_repair_use_case(user) -> RepairDecisionDataReliabilityUseCase:
    """Build the decision reliability repair use case."""

    return RepairDecisionDataReliabilityUseCase(
        provider_repo=_make_provider_repo(),
        provider_factory=_make_provider_factory(),
        macro_fact_repo=MacroFactRepository(),
        indicator_catalog_repo=IndicatorCatalogRepository(),
        price_bar_repo=PriceBarRepository(),
        quote_snapshot_repo=QuoteSnapshotRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
        legacy_macro_repo=LegacyMacroSeriesRepository(),
        pulse_refresher=_build_pulse_refresher(),
        alpha_refresher=_build_alpha_refresher(user),
        alpha_status_reader=_build_alpha_status_reader(user),
    )


def make_sync_macro_use_case() -> SyncMacroUseCase:
    """Build the macro sync use case."""

    return SyncMacroUseCase(
        provider_repo=_make_provider_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=MacroFactRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_price_use_case() -> SyncPriceUseCase:
    """Build the historical price sync use case."""

    return SyncPriceUseCase(
        provider_repo=_make_provider_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=PriceBarRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_quote_use_case() -> SyncQuoteUseCase:
    """Build the quote sync use case."""

    return SyncQuoteUseCase(
        provider_repo=_make_provider_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=QuoteSnapshotRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_fund_nav_use_case() -> SyncFundNavUseCase:
    """Build the fund NAV sync use case."""

    return SyncFundNavUseCase(
        provider_repo=_make_provider_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=FundNavRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_financial_use_case() -> SyncFinancialUseCase:
    """Build the financial facts sync use case."""

    return SyncFinancialUseCase(
        provider_repo=_make_provider_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=FinancialFactRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def get_active_provider_id_by_source(source_type: str) -> int | None:
    """Return the highest-priority active provider id for a source type."""

    providers = _make_provider_repo().get_active_by_type(source_type)
    if not providers:
        return None
    return providers[0].id


def make_sync_valuation_use_case() -> SyncValuationUseCase:
    """Build the valuation sync use case."""

    return SyncValuationUseCase(
        provider_repo=_make_provider_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=ValuationFactRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_sector_membership_use_case() -> SyncSectorMembershipUseCase:
    """Build the sector membership sync use case."""

    return SyncSectorMembershipUseCase(
        provider_repo=_make_provider_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=SectorMembershipRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_news_use_case() -> SyncNewsUseCase:
    """Build the news sync use case."""

    return SyncNewsUseCase(
        provider_repo=_make_provider_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=NewsRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )


def make_sync_capital_flow_use_case() -> SyncCapitalFlowUseCase:
    """Build the capital flow sync use case."""

    return SyncCapitalFlowUseCase(
        provider_repo=_make_provider_repo(),
        provider_factory=_make_provider_factory(),
        fact_repo=CapitalFlowRepository(),
        raw_audit_repo=_make_raw_audit_repo(),
    )
