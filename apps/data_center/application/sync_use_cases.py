"""Provider-to-fact synchronization use cases for Data Center."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar, cast

from apps.data_center.application.dtos import (
    SyncFinancialRequest,
    SyncFundNavRequest,
    SyncMacroBatchRequest,
    SyncMacroBatchResult,
    SyncMacroRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncResult,
    SyncSectorMembershipRequest,
    SyncValuationRequest,
)
from apps.data_center.domain.entities import MacroFact, ProviderConfig, RawAudit
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import (
    FinancialFactRepositoryProtocol,
    FundNavRepositoryProtocol,
    IndicatorCatalogRepositoryProtocol,
    IndicatorUnitRuleRepositoryProtocol,
    MacroFactRepositoryProtocol,
    PriceBarRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    QuoteSnapshotRepositoryProtocol,
    RawAuditRepositoryProtocol,
    SectorMembershipRepositoryProtocol,
    UnifiedDataProviderProtocol,
    ValuationFactRepositoryProtocol,
)

from .macro_fact_governance import MacroFactGovernanceNormalizer
from .macro_publication import PublishMacroBatchUseCase
from .provider_health_recorder import persist_provider_health_metric
from .publication_sync import (
    PublishFinancialBatchUseCase,
    PublishFundNavBatchUseCase,
    PublishPriceBarBatchUseCase,
    PublishQuoteSnapshotBatchUseCase,
    PublishSectorMembershipBatchUseCase,
    PublishValuationBatchUseCase,
)

if TYPE_CHECKING:
    from .sync_news_capital_use_cases import SyncCapitalFlowUseCase, SyncNewsUseCase

FactT = TypeVar("FactT")

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


def _sync_status(stored_count: int) -> tuple[str, str]:
    """Return audit and DTO status without treating zero writes as success."""

    if stored_count > 0:
        return "ok", "success"
    return "noop", "noop"


def _build_sync_audit(
    provider_name: str,
    capability: str,
    request_params: Mapping[str, object],
    status: str,
    row_count: int,
    latency_ms: float,
    error_message: str = "",
) -> RawAudit:
    params_hash = hashlib.sha256(
        json.dumps(dict(request_params), ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()
    return RawAudit(
        provider_name=provider_name,
        capability=capability,
        request_params=dict(request_params),
        status=status,
        row_count=row_count,
        latency_ms=latency_ms,
        error_message=error_message,
        fetched_at=datetime.now(UTC),
        request_params_hash=params_hash,
        redacted=True,
        payload_size_bytes=0,
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
        fact: FactT,
        *,
        source_type: str,
        provider_name: str,
    ) -> FactT:
        updates: dict[str, Any] = {"source": source_type}
        if hasattr(fact, "extra"):
            next_extra = dict(getattr(fact, "extra", {}) or {})
            next_extra["source_type"] = source_type
            next_extra.setdefault("provider_name", provider_name)
            updates["extra"] = next_extra
        return cast(FactT, dataclasses.replace(cast(Any, fact), **updates))

    @classmethod
    def _normalize_fact_sources(
        cls,
        facts: list[FactT],
        *,
        source_type: str,
        provider_name: str,
    ) -> list[FactT]:
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
        output_count: int | None = None,
    ) -> None:
        persist_provider_health_metric(
            self._provider_repo,
            self._provider_registry,
            config,
            capability=capability,
            latency_ms=latency_ms,
            success=success,
            error=error,
            recorded_at=recorded_at,
            output_count=output_count,
        )

    def _record_outcome(
        self,
        config: ProviderConfig,
        *,
        provider_name: str,
        capability: str,
        request_params: Mapping[str, object],
        status: str,
        row_count: int,
        latency_ms: float,
        error_message: str = "",
    ) -> None:
        """Persist one consistent health and raw-audit outcome."""
        if status == "noop" and not error_message:
            error_message = "provider completed without output"
        self._persist_provider_health_metric(
            config,
            capability=capability,
            latency_ms=latency_ms,
            success=status == "ok",
            error=error_message,
            output_count=row_count,
        )
        self._raw_audit_repo.log(
            _build_sync_audit(
                provider_name,
                capability,
                request_params,
                status,
                row_count,
                latency_ms,
                error_message,
            )
        )


class SyncMacroUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: MacroFactRepositoryProtocol,
        catalog_repo: IndicatorCatalogRepositoryProtocol,
        unit_rule_repo: IndicatorUnitRuleRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishMacroBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._normalizer = MacroFactGovernanceNormalizer(catalog_repo, unit_rule_repo)
        self._publication_publisher = publication_publisher

    def _normalize_macro_facts(
        self,
        *,
        indicator_code: str,
        source_type: str,
        provider_name: str,
        facts: list[MacroFact],
    ) -> list[MacroFact]:
        if any(fact.indicator_code != indicator_code for fact in facts):
            raise ValueError(f"Provider returned a mismatched indicator for {indicator_code}")
        return self._normalizer.normalize_many(
            facts,
            source_type=source_type,
            provider_name=provider_name,
        )

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
            if self._publication_publisher is not None and normalized:
                self._publication_publisher.execute(
                    normalized,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._persist_provider_health_metric(
                config,
                capability="macro",
                latency_ms=latency_ms,
                success=stored_count > 0,
                output_count=stored_count,
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
                    audit_status,
                    stored_count,
                    latency_ms,
                )
            )
            return SyncResult("macro", provider.provider_name(), stored_count, result_status)
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
        publication_publisher: PublishPriceBarBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncPriceRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        try:
            bars = provider.fetch_price_history(request.asset_code, request.start, request.end)
            bars = [
                dataclasses.replace(
                    bar,
                    source=str(bar.source or config.source_type).strip(),
                )
                for bar in bars
            ]
            stored_count = self._facts.bulk_upsert(bars)
            if self._publication_publisher is not None and bars:
                self._publication_publisher.execute(
                    bars,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._persist_provider_health_metric(
                config,
                capability="historical_price",
                latency_ms=latency_ms,
                success=stored_count > 0,
                output_count=stored_count,
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
                    audit_status,
                    stored_count,
                    latency_ms,
                )
            )
            return SyncResult(
                "historical_price", provider.provider_name(), stored_count, result_status
            )
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
        publication_publisher: PublishQuoteSnapshotBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

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
            if self._publication_publisher is not None and quotes:
                self._publication_publisher.execute(
                    quotes,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._persist_provider_health_metric(
                config,
                capability="realtime_quote",
                latency_ms=latency_ms,
                success=stored_count > 0,
                output_count=stored_count,
            )
            self._raw_audit_repo.log(
                _build_sync_audit(
                    provider.provider_name(),
                    "realtime_quote",
                    {"asset_codes": request.asset_codes},
                    audit_status,
                    stored_count,
                    latency_ms,
                )
            )
            return SyncResult(
                "realtime_quote", provider.provider_name(), stored_count, result_status
            )
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
        publication_publisher: PublishFundNavBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncFundNavRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {
            "fund_code": request.fund_code,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        }
        try:
            facts = provider.fetch_fund_nav(request.fund_code, request.start, request.end)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(facts)
            if self._publication_publisher is not None and facts:
                self._publication_publisher.execute(
                    facts,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="fund_nav",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult("fund_nav", provider.provider_name(), stored_count, result_status)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="fund_nav",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


class SyncFinancialUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: FinancialFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishFinancialBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncFinancialRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {"asset_code": request.asset_code, "periods": request.periods}
        try:
            facts = provider.fetch_financials(request.asset_code, periods=request.periods)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(facts)
            if self._publication_publisher is not None and facts:
                self._publication_publisher.execute(
                    facts,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="financial",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult("financial", provider.provider_name(), stored_count, result_status)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="financial",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


class SyncValuationUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: ValuationFactRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishValuationBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

    def execute(self, request: SyncValuationRequest) -> SyncResult:
        config, provider = self._get_provider(request.provider_id)
        started = datetime.now(UTC)
        params = {
            "asset_code": request.asset_code,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        }
        try:
            facts = provider.fetch_valuations(request.asset_code, request.start, request.end)
            facts = self._normalize_fact_sources(
                facts,
                source_type=config.source_type,
                provider_name=provider.provider_name(),
            )
            stored_count = self._facts.bulk_upsert(facts)
            if self._publication_publisher is not None and facts:
                self._publication_publisher.execute(
                    facts,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="valuation",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult("valuation", provider.provider_name(), stored_count, result_status)
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


class SyncSectorMembershipUseCase(_BaseSyncUseCase):
    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: SectorMembershipRepositoryProtocol,
        raw_audit_repo: RawAuditRepositoryProtocol,
        publication_publisher: PublishSectorMembershipBatchUseCase | None = None,
    ) -> None:
        super().__init__(provider_repo, provider_registry, raw_audit_repo)
        self._facts = fact_repo
        self._publication_publisher = publication_publisher

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
            if self._publication_publisher is not None and facts:
                self._publication_publisher.execute(
                    facts,
                    provider_name=provider.provider_name(),
                )
            audit_status, result_status = _sync_status(stored_count)
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="sector_membership",
                request_params=params,
                status=audit_status,
                row_count=stored_count,
                latency_ms=latency_ms,
            )
            return SyncResult(
                "sector_membership", provider.provider_name(), stored_count, result_status
            )
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
            latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            self._record_outcome(
                config,
                provider_name=provider.provider_name(),
                capability="sector_membership",
                request_params=params,
                status="error",
                row_count=0,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
            raise


def __getattr__(name: str) -> object:
    """Resolve moved news/capital sync classes without a sibling import cycle."""

    if name in {"SyncCapitalFlowUseCase", "SyncNewsUseCase"}:
        from . import sync_news_capital_use_cases

        return getattr(sync_news_capital_use_cases, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
