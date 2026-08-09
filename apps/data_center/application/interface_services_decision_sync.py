"""Application-side dependency builders for data_center interface endpoints."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from apps.data_center.application.dtos import (
    LatestQuoteRequest,
    SyncNewsRequest,
    SyncQuoteRequest,
    SyncResult,
)
from apps.data_center.application.on_demand import OnDemandDataCenterService
from apps.data_center.application.provider_capabilities import SOURCE_TYPE_CAPABILITIES
from apps.data_center.composition import (
    CanonicalPublicationRepository,
    CapitalFlowRepository,
    FinancialFactRepository,
    FundNavRepository,
    MarketThermometerSnapshotRepository,
    NewsRepository,
    PriceBarRepository,
    PublicationPolicyRepository,
    QuoteSnapshotRepository,
    RawAuditRepository,
    SectorMembershipRepository,
    ValuationFactRepository,
    build_provider_registry_for_repo,
)
from apps.data_center.domain.enums import DataCapability
from core.exceptions import DataFetchError

from .current_valuation_sync import SyncCurrentValuationBatchUseCase
from .interface_services import (
    _build_alpha_refresher,
    _get_provider_registry,
    _json_object,
    _make_indicator_catalog_repo,
    _make_indicator_unit_rule_repo,
    _make_macro_fact_repository,
    _make_provider_repo,
    _make_raw_audit_repo,
    make_calculate_market_thermometer_use_case,
    refresh_pulse_snapshot,
)
from .macro_publication import PublishMacroBatchUseCase
from .publication_sync import (
    PublishCapitalFlowBatchUseCase,
    PublishFinancialBatchUseCase,
    PublishFundNavBatchUseCase,
    PublishNewsBatchUseCase,
    PublishPriceBarBatchUseCase,
    PublishQuoteSnapshotBatchUseCase,
    PublishSectorMembershipBatchUseCase,
    PublishValuationBatchUseCase,
)
from .use_cases import (
    DEFAULT_DECISION_ASSET_CODES,
    QueryLatestQuoteUseCase,
    RepairDecisionDataReliabilityUseCase,
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


def _build_pulse_refresher() -> Callable[[date], Any]:
    def _refresh(target_date: date) -> Any:
        return refresh_pulse_snapshot(target_date=target_date)

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

        from . import interface_services as _facade

        data = _facade.load_alpha_homepage_data(
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
        macro_fact_repo=_make_macro_fact_repository(),
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

    macro_repository = _make_macro_fact_repository()
    return SyncMacroUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=macro_repository,
        catalog_repo=_make_indicator_catalog_repo(),
        unit_rule_repo=_make_indicator_unit_rule_repo(),
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishMacroBatchUseCase(
            fact_repository=macro_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
    )


def make_sync_macro_batch_use_case() -> SyncMacroBatchUseCase:
    """Build the canonical provider-selected macro batch sync use case."""

    provider_repo = _make_provider_repo()
    provider_registry = _get_provider_registry()
    macro_repository = _make_macro_fact_repository()
    sync_use_case = SyncMacroUseCase(
        provider_repo=provider_repo,
        provider_registry=provider_registry,
        fact_repo=macro_repository,
        catalog_repo=_make_indicator_catalog_repo(),
        unit_rule_repo=_make_indicator_unit_rule_repo(),
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishMacroBatchUseCase(
            fact_repository=macro_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
    )
    return SyncMacroBatchUseCase(
        provider_repo=provider_repo,
        provider_registry=provider_registry,
        sync_use_case=sync_use_case,
    )


def make_sync_price_use_case() -> SyncPriceUseCase:
    """Build the historical price sync use case."""

    price_repository = PriceBarRepository()
    return SyncPriceUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=price_repository,
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishPriceBarBatchUseCase(
            fact_repository=price_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
    )


def make_sync_quote_use_case() -> SyncQuoteUseCase:
    """Build the quote sync use case."""

    quote_repository = QuoteSnapshotRepository()
    return SyncQuoteUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=quote_repository,
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishQuoteSnapshotBatchUseCase(
            fact_repository=quote_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
    )


def make_sync_fund_nav_use_case() -> SyncFundNavUseCase:
    """Build the fund NAV sync use case."""

    fund_nav_repository = FundNavRepository()
    return SyncFundNavUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=fund_nav_repository,
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishFundNavBatchUseCase(
            fact_repository=fund_nav_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
    )


def make_sync_financial_use_case() -> SyncFinancialUseCase:
    """Build the financial facts sync use case."""

    financial_repository = FinancialFactRepository()
    return SyncFinancialUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=financial_repository,
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishFinancialBatchUseCase(
            fact_repository=financial_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
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

    valuation_repository = ValuationFactRepository()
    return SyncValuationUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=valuation_repository,
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishValuationBatchUseCase(
            fact_repository=valuation_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
    )


def make_sync_current_valuation_batch_use_case() -> SyncCurrentValuationBatchUseCase:
    """Build the current valuation batch sync use case."""

    valuation_repository = ValuationFactRepository()
    return SyncCurrentValuationBatchUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=valuation_repository,
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishValuationBatchUseCase(
            fact_repository=valuation_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
    )


def make_sync_sector_membership_use_case() -> SyncSectorMembershipUseCase:
    """Build the sector membership sync use case."""

    membership_repository = SectorMembershipRepository()
    return SyncSectorMembershipUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=membership_repository,
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishSectorMembershipBatchUseCase(
            fact_repository=membership_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
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

    news_repository = NewsRepository()
    return SyncNewsUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=news_repository,
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishNewsBatchUseCase(
            fact_repository=news_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
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

    flow_repository = CapitalFlowRepository()
    return SyncCapitalFlowUseCase(
        provider_repo=_make_provider_repo(),
        provider_registry=_get_provider_registry(),
        fact_repo=flow_repository,
        raw_audit_repo=_make_raw_audit_repo(),
        publication_publisher=PublishCapitalFlowBatchUseCase(
            fact_repository=flow_repository,
            publication_repository=CanonicalPublicationRepository(),
            policy_repository=PublicationPolicyRepository(),
        ),
    )
