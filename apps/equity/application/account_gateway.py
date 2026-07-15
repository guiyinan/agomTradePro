"""Register Equity market access for Account stress testing."""

from __future__ import annotations

from apps.account.application.business_provider_gateway import (
    register_equity_market_adapter_factory,
)

from . import repository_provider


def register_equity_account_gateway() -> None:
    """Register the owning Equity historical-market adapter factory."""

    register_equity_market_adapter_factory(repository_provider.get_tushare_stock_adapter)


__all__ = ["register_equity_account_gateway"]
