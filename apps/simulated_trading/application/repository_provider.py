"""Repository providers for simulated trading application services."""

from __future__ import annotations

from apps.simulated_trading.infrastructure.repositories import (
    DjangoFeeConfigRepository,
    DjangoInspectionRepository,
    DjangoPositionRepository,
    DjangoSimulatedAccountRepository,
    DjangoTradeRepository,
)


def get_simulated_account_repository() -> DjangoSimulatedAccountRepository:
    """Return the default simulated account repository."""

    return DjangoSimulatedAccountRepository()


def get_simulated_position_repository() -> DjangoPositionRepository:
    """Return the default simulated position repository."""

    return DjangoPositionRepository()


def get_simulated_trade_repository() -> DjangoTradeRepository:
    """Return the default simulated trade repository."""

    return DjangoTradeRepository()


def get_simulated_fee_config_repository() -> DjangoFeeConfigRepository:
    """Return the default simulated fee config repository."""

    return DjangoFeeConfigRepository()


def get_simulated_inspection_repository() -> DjangoInspectionRepository:
    """Return the default simulated inspection repository."""

    return DjangoInspectionRepository()
