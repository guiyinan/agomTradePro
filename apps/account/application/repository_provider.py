"""Account repository providers for application consumers."""

from __future__ import annotations

from apps.account.infrastructure.providers import (
    AccountInterfaceRepository,
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
)


def get_account_interface_repository() -> AccountInterfaceRepository:
    """Return the account interface repository."""

    return AccountInterfaceRepository()


def get_account_repository() -> AccountRepository:
    """Return the account repository."""

    return AccountRepository()


def get_account_position_repository() -> PositionRepository:
    """Return the account position repository."""

    return PositionRepository()


def get_portfolio_repository() -> PortfolioRepository:
    """Return the account portfolio repository."""

    return PortfolioRepository()
