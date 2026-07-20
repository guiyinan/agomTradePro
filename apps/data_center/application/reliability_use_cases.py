"""Decision-data reliability repair orchestration for Data Center."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from apps.data_center.application.dtos import (
    DecisionReliabilityRepairReport,
    DecisionReliabilityRepairRequest,
    DecisionReliabilitySection,
    LatestQuoteRequest,
    MacroSeriesRequest,
    SyncMacroRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
)
from apps.data_center.application.provider_capabilities import SOURCE_TYPE_CAPABILITIES
from apps.data_center.application.query_use_cases import (
    QueryLatestQuoteUseCase,
    QueryMacroSeriesUseCase,
)
from apps.data_center.application.sync_use_cases import (
    RECOVERABLE_DATA_CENTER_EXCEPTIONS,
    SyncMacroUseCase,
    SyncPriceUseCase,
    SyncQuoteUseCase,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import (
    IndicatorCatalogRepositoryProtocol,
    IndicatorUnitRuleRepositoryProtocol,
    MacroFactRepositoryProtocol,
    PriceBarRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    QuoteSnapshotRepositoryProtocol,
    RawAuditRepositoryProtocol,
)
from shared.date_utils import business_day_age

logger = logging.getLogger(__name__)

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
TUSHARE_CPI_INDICATORS = frozenset(
    {
        "CN_CPI",
        "CN_CPI_NATIONAL_YOY",
        "CN_CPI_NATIONAL_MOM",
        "CN_CPI_URBAN_YOY",
        "CN_CPI_URBAN_MOM",
        "CN_CPI_RURAL_YOY",
        "CN_CPI_RURAL_MOM",
    }
)
_SOURCE_TYPE_CAPABILITIES = SOURCE_TYPE_CAPABILITIES


class RepairDecisionDataReliabilityUseCase:
    """Repair and re-check the data chain required for actionable decisions."""

    def __init__(
        self,
        *,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry,
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
        self._provider_registry = provider_registry
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
        macro_status = self._run_repair_section(
            "macro",
            lambda: self._repair_macro_inputs(request, target_date, macro_codes),
        )
        quote_status = self._run_repair_section(
            "quote",
            lambda: self._repair_quote_inputs(request, target_date, asset_codes),
        )
        pulse_status = self._run_repair_section(
            "pulse",
            lambda: self._repair_pulse(request, target_date),
        )
        alpha_status = self._run_repair_section(
            "alpha",
            lambda: self._repair_alpha(request, target_date),
        )

        return DecisionReliabilityRepairReport(
            target_date=target_date,
            portfolio_id=request.portfolio_id,
            macro_status=macro_status,
            quote_status=quote_status,
            pulse_status=pulse_status,
            alpha_status=alpha_status,
            provider_bootstrap=provider_bootstrap,
        )

    def _run_repair_section(
        self,
        section_name: str,
        callback: Callable[[], DecisionReliabilitySection],
    ) -> DecisionReliabilitySection:
        """Run one repair section without letting it abort later sections."""

        try:
            return callback()
        except Exception as exc:
            logger.exception("Decision reliability %s repair failed", section_name)
            return DecisionReliabilitySection(
                status="failed",
                must_not_use_for_decision=True,
                blocked_reasons=[f"{section_name} 修复异常: {exc}"],
                details={
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                },
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
                    provider_registry=self._provider_registry,
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
                    provider_registry=self._provider_registry,
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
                        provider_registry=self._provider_registry,
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
                lag_days = business_day_age(latest_bar.bar_date, target_date)
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
        if indicator_code in TUSHARE_CPI_INDICATORS:
            provider = self._select_provider_by_types(
                ("tushare",),
                DataCapability.MACRO.value,
            )
            if provider is not None and str(provider.api_key or "").strip():
                return provider
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


__all__ = [
    "AKSHARE_MACRO_INDICATORS",
    "DEFAULT_DECISION_ASSET_CODES",
    "DEFAULT_DECISION_MACRO_INDICATORS",
    "RepairDecisionDataReliabilityUseCase",
    "TUSHARE_CPI_INDICATORS",
]
