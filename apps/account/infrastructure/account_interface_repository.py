"""Compatibility owner for Account interface repository operations."""

from apps.account.infrastructure.account_interface_administration_repository import (
    AccountInterfaceAdministrationRepositoryMixin,
)
from apps.account.infrastructure.account_interface_portfolio_repository import (
    AccountInterfacePortfolioRepositoryMixin,
)
from apps.account.infrastructure.account_interface_registration_repository import (
    AccountInterfaceRegistrationRepositoryMixin,
)


class AccountInterfaceRepository(
    AccountInterfaceRegistrationRepositoryMixin,
    AccountInterfacePortfolioRepositoryMixin,
    AccountInterfaceAdministrationRepositoryMixin,
):
    """Compose stable Account interface operations from focused owners."""
