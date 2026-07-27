"""Account-owned gateway for portfolio and trading capabilities."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any, TypeVar

from apps.account.application.market_price_contracts import MarketPriceProvider
from apps.account.application.portfolio_api_contracts import (
    PortfolioApiRepository,
    UnifiedPositionService,
)

_ProviderT = TypeVar("_ProviderT")

_portfolio_repository_factory: Callable[[], PortfolioApiRepository] | None = None
_position_service_factory: Callable[[], UnifiedPositionService] | None = None
_price_provider_factory: Callable[[int], MarketPriceProvider] | None = None
_default_accounts_provisioner: Callable[[Any, Decimal], None] | None = None
_investment_accounts_reader: Callable[[int], list[dict[str, Any]]] | None = None
_portfolio_account_resolver: Callable[[int], int | None] | None = None
_view_resolver: Callable[[str], Any] | None = None


def configure_simulated_trading_gateway(
    *,
    portfolio_repository_factory: Callable[[], PortfolioApiRepository],
    position_service_factory: Callable[[], UnifiedPositionService],
    price_provider_factory: Callable[[int], MarketPriceProvider],
    default_accounts_provisioner: Callable[[Any, Decimal], None],
    investment_accounts_reader: Callable[[int], list[dict[str, Any]]],
    portfolio_account_resolver: Callable[[int], int | None],
    view_resolver: Callable[[str], Any],
) -> None:
    """Register Simulated Trading implementations for Account consumers."""

    global _portfolio_repository_factory
    global _position_service_factory
    global _price_provider_factory
    global _default_accounts_provisioner
    global _investment_accounts_reader
    global _portfolio_account_resolver
    global _view_resolver
    _portfolio_repository_factory = portfolio_repository_factory
    _position_service_factory = position_service_factory
    _price_provider_factory = price_provider_factory
    _default_accounts_provisioner = default_accounts_provisioner
    _investment_accounts_reader = investment_accounts_reader
    _portfolio_account_resolver = portfolio_account_resolver
    _view_resolver = view_resolver


def _require(provider: _ProviderT | None, capability: str) -> _ProviderT:
    """Return a configured provider or raise a capability-specific error."""

    if provider is None:
        raise RuntimeError(f"Simulated Trading provider is not configured: {capability}")
    return provider


def build_portfolio_api_repository() -> PortfolioApiRepository:
    """Build the portfolio bridge repository owned by Simulated Trading."""

    factory = _require(_portfolio_repository_factory, "portfolio_repository")
    return factory()


def get_unified_position_service() -> UnifiedPositionService:
    """Return the unified position service."""

    factory = _require(_position_service_factory, "position_service")
    return factory()


def build_market_price_provider(cache_ttl_minutes: int) -> MarketPriceProvider:
    """Build the trading price provider used by Account compatibility services."""

    factory = _require(_price_provider_factory, "price_provider")
    return factory(cache_ttl_minutes)


def provision_default_trading_accounts(user: Any, initial_capital: Decimal) -> None:
    """Provision the default real and simulated trading accounts for a user."""

    provider = _require(_default_accounts_provisioner, "default_accounts")
    provider(user, initial_capital)


def list_investment_account_payloads(user_id: int) -> list[dict[str, Any]]:
    """Return investment-account summaries for the Account profile UI."""

    provider = _require(_investment_accounts_reader, "investment_accounts")
    return provider(user_id)


def get_unified_account_id_for_portfolio(portfolio_id: int) -> int | None:
    """Resolve the unified trading account mapped to a legacy portfolio."""

    provider = _require(_portfolio_account_resolver, "portfolio_account")
    return provider(portfolio_id)


def get_simulated_trading_view(view_key: str) -> Any:
    """Resolve a canonical trading API view without importing its owner."""

    provider = _require(_view_resolver, "view_resolver")
    return provider(view_key)


__all__ = [
    "build_market_price_provider",
    "build_portfolio_api_repository",
    "configure_simulated_trading_gateway",
    "get_simulated_trading_view",
    "get_unified_account_id_for_portfolio",
    "get_unified_position_service",
    "list_investment_account_payloads",
    "provision_default_trading_accounts",
]
