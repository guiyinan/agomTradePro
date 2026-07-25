"""Repository provider for backtest application orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from apps.backtest.infrastructure.providers import (
    DjangoBacktestRepository as DjangoBacktestRepository,
)


class AssetPriceAdapterProtocol(Protocol):
    """Price lookup surface required by backtest readers."""

    def get_price(self, asset_class: str, as_of_date: date) -> float | None: ...

    def get_prices(
        self,
        asset_class: str,
        start_date: date,
        end_date: date,
    ) -> list[Any]: ...


def get_backtest_repository() -> DjangoBacktestRepository:
    """Return the configured backtest repository implementation."""

    return DjangoBacktestRepository()


def get_close_price_series_reader() -> Callable[[str, date, date], list[tuple[date, float]]]:
    """Return the configured historical close-price reader."""

    from core.integration.price_history import fetch_close_price_series_from_data_center

    return fetch_close_price_series_from_data_center


def create_default_price_adapter(
    *,
    tushare_token: str | None,
    tushare_http_url: str | None = None,
) -> AssetPriceAdapterProtocol:
    """Return the default backtest price adapter."""

    from apps.backtest.infrastructure.adapters.composite_price_adapter import (
        create_default_price_adapter as _create_default_price_adapter,
    )

    return _create_default_price_adapter(
        tushare_token=tushare_token,
        tushare_http_url=tushare_http_url,
    )


def build_default_price_reader() -> Callable[[str, date], float | None]:
    """Build a lazy price reader that reuses one adapter per execution."""

    adapter: AssetPriceAdapterProtocol | None = None

    def get_asset_price(asset_class: str, as_of_date: date) -> float | None:
        nonlocal adapter
        if adapter is None:
            from shared.config.secrets import get_secrets

            try:
                data_sources = get_secrets().data_sources
            except ValueError:
                data_sources = None
            adapter = create_default_price_adapter(
                tushare_token=(data_sources.tushare_token if data_sources else None),
                tushare_http_url=(data_sources.tushare_http_url if data_sources else None),
            )
        return adapter.get_price(asset_class, as_of_date)

    return get_asset_price


def build_default_regime_reader() -> Callable[[date], dict[str, object] | None]:
    """Build a regime reader that reuses one repository per execution."""

    from apps.regime.application.repository_provider import get_regime_repository

    regime_repository = get_regime_repository()

    def get_regime(as_of_date: date) -> dict[str, object] | None:
        snapshot = regime_repository.get_regime_by_date(as_of_date)
        if snapshot is None:
            return None
        return {
            "dominant_regime": snapshot.dominant_regime,
            "confidence": snapshot.confidence,
            "growth_momentum_z": snapshot.growth_momentum_z,
            "inflation_momentum_z": snapshot.inflation_momentum_z,
            "distribution": snapshot.distribution,
        }

    return get_regime
