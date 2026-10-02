"""Composition helpers for capability-qualified model market providers."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from apps.data_center.application.model_history_preparation import (
    ModelHistoryFetchAuditPort,
    ModelHistoryReferenceSnapshot,
)
from apps.data_center.application.model_market_data import ModelMarketDataService, ModelMarketRoute
from apps.data_center.domain.enums import DataCapability, PriceAdjustment
from apps.data_center.domain.model_market_data import ModelDailyBar, ModelMarketDataPort
from apps.data_center.domain.protocols import PriceBarRepositoryProtocol
from apps.data_center.infrastructure.provider_registry import ProviderRegistry
from core.exceptions import ConfigurationError


@runtime_checkable
class _ModelProvider(Protocol):
    def provider_name(self) -> str: ...
    def provider_source(self) -> str: ...
    def provider_id(self) -> int: ...
    def model_market_source(
        self,
        *,
        tolerance: float,
        history_fetch_audit: ModelHistoryFetchAuditPort | None = None,
    ) -> ModelMarketDataPort: ...


def build_model_market_service(
    registry: ProviderRegistry,
    repository: PriceBarRepositoryProtocol,
    settings: dict[str, object],
    history_fetch_audit: ModelHistoryFetchAuditPort | None = None,
) -> ModelMarketDataPort:
    """Resolve configured routes; callers never receive provider SDKs."""
    enabled = settings.get("enable_failover")
    tolerance = settings.get("failover_tolerance")
    default_source = settings.get("default_source")
    if (
        settings.get("status") != "active"
        or not isinstance(enabled, bool)
        or isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or default_source not in {"akshare", "tushare", "failover"}
    ):
        raise ConfigurationError(
            "Data Center provider policy unavailable", code="MODEL_MARKET_CONFIG_UNAVAILABLE"
        )
    providers = [
        provider
        for provider in registry.get_providers(DataCapability.HISTORICAL_PRICE)
        if isinstance(provider, _ModelProvider)
    ]
    if default_source != "failover":
        providers.sort(key=lambda provider: provider.provider_source() != default_source)
        if not enabled:
            providers = [
                provider for provider in providers if provider.provider_source() == default_source
            ]
    if not providers:
        raise ConfigurationError(
            "No configured model-market route", code="MODEL_MARKET_CONFIG_UNAVAILABLE"
        )
    routes = tuple(
        ModelMarketRoute(
            provider.provider_name(),
            provider.model_market_source(
                tolerance=float(tolerance), history_fetch_audit=history_fetch_audit
            ),
            requires_reference=(
                index > 0
                or (default_source != "failover" and provider.provider_source() != default_source)
            ),
            provider_id=provider.provider_id(),
        )
        for index, provider in enumerate(providers)
    )

    def reference_history(asset_code: str, start: date, end: date) -> tuple[ModelDailyBar, ...]:
        return tuple(
            ModelDailyBar(
                asset_code=bar.asset_code,
                trade_date=bar.bar_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                change_percent=0.0,
                adjustment_factor=None,
                source=bar.source,
                amount=bar.amount,
            )
            for bar in repository.get_bars(asset_code, start=start, end=end, limit=5000)
            if bar.adjustment == PriceAdjustment.NONE and bar.source and bar.volume is not None
        )

    def reference_history_snapshot(
        asset_codes: tuple[str, ...], start: date, end: date
    ) -> ModelHistoryReferenceSnapshot:
        """Capture all source references in one repository read before preparation."""

        bars = repository.get_bars_for_assets(asset_codes, start=start, end=end, limit=5000)
        return ModelHistoryReferenceSnapshot.from_bars(asset_codes, start, end, bars)

    per_asset_limit = settings.get("max_per_asset_preparation_assets")
    if per_asset_limit is not None and (
        isinstance(per_asset_limit, bool)
        or not isinstance(per_asset_limit, int)
        or per_asset_limit <= 0
    ):
        raise ConfigurationError(
            "Per-asset preparation limit is invalid",
            code="MODEL_MARKET_PER_ASSET_LIMIT_INVALID",
        )

    return ModelMarketDataService(
        routes,
        enable_failover=enabled,
        tolerance=float(tolerance),
        reference_history=reference_history,
        reference_history_snapshot=reference_history_snapshot,
        history_fetch_audit=history_fetch_audit,
        max_per_asset_preparation_assets=per_asset_limit,
    )
