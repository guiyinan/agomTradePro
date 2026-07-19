"""Provider-to-fact synchronization use cases for Data Center."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any

from apps.data_center.application.dtos import (
    SyncCapitalFlowRequest,
    SyncFinancialRequest,
    SyncFundNavRequest,
    SyncMacroBatchRequest,
    SyncMacroBatchResult,
    SyncMacroRequest,
    SyncNewsRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncResult,
    SyncSectorMembershipRequest,
    SyncValuationRequest,
)
from apps.data_center.domain.entities import ProviderConfig, RawAudit
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import (
    CapitalFlowRepositoryProtocol,
    FinancialFactRepositoryProtocol,
    FundNavRepositoryProtocol,
    IndicatorCatalogRepositoryProtocol,
    IndicatorUnitRuleRepositoryProtocol,
    MacroFactRepositoryProtocol,
    NewsRepositoryProtocol,
    PriceBarRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    QuoteSnapshotRepositoryProtocol,
    RawAuditRepositoryProtocol,
    SectorMembershipRepositoryProtocol,
    UnifiedDataProviderProtocol,
    ValuationFactRepositoryProtocol,
)

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
        fetched_at=datetime.now(UTC),
    )


class _BaseSyncUseCase:
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_registry = provider_registry
        self._raw_audit_repo = raw_audit_repo

    def _get_provider(self, provider_id: int) -> tuple[ProviderConfig, UnifiedDataProviderProtocol]:
        config = self._provider_repo.get_by_id(provider_id)
        if config is None:
            raise ValueError(f"Provider not found: {provider_id}")
        provider = self._provider_registry.get_by_id(provider_id)
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
        recorded = recorded_at or datetime.now(UTC)
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
        try:
            runtime_capability = DataCapability(capability)
        except ValueError:
            return
        if success:
            self._provider_registry.record_success(
                config.name,
                runtime_capability,
                latency_ms,
            )
        else:
            self._provider_registry.record_failure(config.name, runtime_capability)


class SyncMacroUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: MacroFactRepositoryProtocol,
        catalog_repo: IndicatorCatalogRepositoryProtocol,
        unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
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
        started = datetime.now(UTC)
        try:
            facts = provider.fetch_macro_series(request.indicator_code, request.start, request.end)
            normalized = self._normalize_macro_facts(
                indicator_code=request.indicator_code,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
                facts=facts,
            )
            stored_count = self._facts.bulk_upsert(normalized)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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


class SyncMacroBatchUseCase:
    """Select one configured macro provider and synchronize an indicator batch."""

    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        sync_use_case: SyncMacroUseCase,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_registry = provider_registry
        self._sync_use_case = sync_use_case

    def execute(self, request: SyncMacroBatchRequest) -> SyncMacroBatchResult:
        config = self._select_provider(request.source)
        if config.id is None:
            raise ValueError(f"Provider has no persistent id: {config.name}")

        stored_count = 0
        errors: list[str] = []
        for indicator_code in request.indicator_codes:
            try:
                result = self._sync_use_case.execute(
                    SyncMacroRequest(
                        provider_id=config.id,
                        indicator_code=indicator_code,
                        start=request.start,
                        end=request.end,
                    )
                )
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                errors.append(f"{indicator_code}: {exc}")
                continue
            stored_count += result.stored_count

        return SyncMacroBatchResult(
            provider_name=config.name,
            stored_count=stored_count,
            errors=errors,
        )

    def _select_provider(self, source: str | None) -> ProviderConfig:
        requested = source.strip().lower() if source else ""
        configs = sorted(
            (config for config in self._provider_repo.list_all() if config.is_active),
            key=lambda config: config.priority,
        )
        for config in configs:
            if requested and requested not in {config.name.lower(), config.source_type.lower()}:
                continue
            if config.id is None:
                continue
            provider = self._provider_registry.get_by_id(config.id)
            if provider is not None and provider.supports(DataCapability.MACRO):
                return config
        suffix = f" for source {source!r}" if source else ""
        raise ValueError(f"No active macro provider configured{suffix}")


class SyncPriceUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: PriceBarRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncPriceRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        try:
            bars = provider.fetch_price_history(request.asset_code, request.start, request.end)
            bars = self._normalize_fact_sources(
                bars,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(bars)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
        provider_registry: ProviderRegistryProtocol,
        fact_repo: QuoteSnapshotRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncQuoteRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        try:
            quotes = provider.fetch_quote_snapshots(request.asset_codes)
            quotes = self._normalize_fact_sources(
                quotes,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(quotes)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
        provider_registry: ProviderRegistryProtocol,
        fact_repo: FundNavRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncFundNavRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        try:
            facts = provider.fetch_fund_nav(request.fund_code, request.start, request.end)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
        provider_registry: ProviderRegistryProtocol,
        fact_repo: FinancialFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncFinancialRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        try:
            facts = provider.fetch_financials(request.asset_code, periods=request.periods)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
        provider_registry: ProviderRegistryProtocol,
        fact_repo: ValuationFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncValuationRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        try:
            facts = provider.fetch_valuations(request.asset_code, request.start, request.end)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(facts)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
        provider_registry: ProviderRegistryProtocol,
        fact_repo: SectorMembershipRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo

    def execute(self, request: SyncSectorMembershipRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
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
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
        provider_registry: ProviderRegistryProtocol,
        fact_repo: NewsRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo

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
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(), "news", params, "ok", stored_count, latency_ms
                )
            )
            return SyncResult("news", provider.provider_name(), stored_count, "success")
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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
        provider_registry: ProviderRegistryProtocol,
        fact_repo: CapitalFlowRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo

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
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(), "capital_flow", params, "ok", stored_count, latency_ms
                )
            )
            return SyncResult("capital_flow", provider.provider_name(), stored_count, "success")
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
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

__all__ = [
    "RECOVERABLE_DATA_CENTER_EXCEPTIONS",
    "SyncCapitalFlowUseCase",
    "SyncFinancialUseCase",
    "SyncFundNavUseCase",
    "SyncMacroUseCase",
    "SyncNewsUseCase",
    "SyncPriceUseCase",
    "SyncQuoteUseCase",
    "SyncSectorMembershipUseCase",
    "SyncValuationUseCase",
]
