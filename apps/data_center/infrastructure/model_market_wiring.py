"""Composition helpers for capability-qualified model market providers."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from apps.data_center.application.model_market_data import ModelMarketDataService, ModelMarketRoute
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import DataCapability, PriceAdjustment
from apps.data_center.domain.model_market_data import ModelDailyBar, ModelMarketDataPort
from apps.data_center.domain.protocols import PriceBarRepositoryProtocol
from apps.data_center.infrastructure.provider_registry import ProviderRegistry
from core.exceptions import ConfigurationError


@runtime_checkable
class _ModelProvider(Protocol):
    def provider_name(self) -> str: ...
    def provider_source(self) -> str: ...
    def model_market_source(self, *, tolerance: float) -> ModelMarketDataPort: ...


def build_model_market_service(
    registry: ProviderRegistry,
    repository: PriceBarRepositoryProtocol,
    settings: dict[str, object],
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
            provider.model_market_source(tolerance=float(tolerance)),
            requires_reference=(
                default_source != "failover" and provider.provider_source() != default_source
            ),
        )
        for provider in providers
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
                volume=bar.volume or 0.0,
                change_percent=0.0,
                adjustment_factor=None,
                source=bar.source,
                amount=bar.amount,
            )
            for bar in repository.get_bars(asset_code, start=start, end=end, limit=5000)
            if bar.adjustment == PriceAdjustment.NONE and bar.source
        )

    def store_history(rows: tuple[ModelDailyBar, ...]) -> None:
        repository.bulk_upsert(
            [
                PriceBar(
                    asset_code=row.asset_code,
                    bar_date=row.trade_date,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    amount=row.amount,
                    source=row.source,
                    adjustment=PriceAdjustment.NONE,
                )
                for row in rows
            ]
        )

    return ModelMarketDataService(
        routes,
        enable_failover=enabled,
        tolerance=float(tolerance),
        reference_history=reference_history,
        store_history=store_history,
    )
