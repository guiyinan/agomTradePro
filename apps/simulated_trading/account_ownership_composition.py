"""Public composition for observing the live owner of a physical account row."""

from apps.simulated_trading.application.current_account_ownership import (
    CurrentAccountOwnershipReader,
)
from apps.simulated_trading.infrastructure.current_account_ownership import (
    DjangoCurrentAccountOwnershipReader,
)


def build_current_account_ownership_reader(
    *, using: str = "default"
) -> CurrentAccountOwnershipReader:
    """Build the typed same-alias observation port without issuing authority."""
    return DjangoCurrentAccountOwnershipReader(using=using)
