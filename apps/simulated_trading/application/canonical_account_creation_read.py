"""Owner-scoped physical reads needed by canonical creation and replay."""

from typing import Protocol

from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount


class CanonicalAccountCreationReader(Protocol):
    """Read current rows inside the same user-serialized creation transaction."""

    def name_exists(self, *, user_id: int, account_name: str) -> bool:
        """Check the existing owner/name rule, including inactive accounts."""
        ...

    def read_owned(
        self, *, user_id: int, account_id: int, account_type: AccountType
    ) -> SimulatedAccount | None:
        """Lock and read an active row only when current owner and type match."""
        ...


__all__ = ["CanonicalAccountCreationReader"]
