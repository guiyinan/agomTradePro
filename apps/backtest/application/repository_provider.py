"""Repository provider for backtest application orchestration."""

from __future__ import annotations

from datetime import date
from typing import Callable

from apps.backtest.infrastructure.providers import DjangoBacktestRepository


def get_backtest_repository() -> DjangoBacktestRepository:
    """Return the configured backtest repository implementation."""

    return DjangoBacktestRepository()


def get_close_price_series_reader() -> Callable[[str, date, date], list[tuple[date, float]]]:
    """Return the configured historical close-price reader."""

    from core.integration.price_history import fetch_close_price_series_from_data_center

    return fetch_close_price_series_from_data_center


def create_default_price_adapter(*, tushare_token: str, tushare_http_url: str | None = None):
    """Return the default backtest price adapter."""

    from apps.backtest.infrastructure.adapters.composite_price_adapter import (
        create_default_price_adapter as _create_default_price_adapter,
    )

    return _create_default_price_adapter(
        tushare_token=tushare_token,
        tushare_http_url=tushare_http_url,
    )
