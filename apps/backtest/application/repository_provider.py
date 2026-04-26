"""Repository provider for backtest application orchestration."""

from __future__ import annotations

from apps.backtest.infrastructure.providers import DjangoBacktestRepository


def get_backtest_repository() -> DjangoBacktestRepository:
    """Return the configured backtest repository implementation."""

    return DjangoBacktestRepository()


def create_default_price_adapter(*, tushare_token: str, tushare_http_url: str | None = None):
    """Return the default backtest price adapter."""

    from apps.backtest.infrastructure.adapters.composite_price_adapter import (
        create_default_price_adapter as _create_default_price_adapter,
    )

    return _create_default_price_adapter(
        tushare_token=tushare_token,
        tushare_http_url=tushare_http_url,
    )
