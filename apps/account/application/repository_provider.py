"""Account repository providers for application consumers."""

from __future__ import annotations

from apps.account.infrastructure.repositories import AccountInterfaceRepository, PositionRepository


def get_account_interface_repository() -> AccountInterfaceRepository:
    """Return the account interface repository."""

    return AccountInterfaceRepository()


def get_account_position_repository() -> PositionRepository:
    """Return the account position repository."""

    return PositionRepository()
