"""Typed live row observations for revalidating an existing ownership decision."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.simulated_trading.domain.entities import AccountType
from core.exceptions import AgomTradeProException


class CurrentAccountOwnershipUnavailable(AgomTradeProException):
    """The live ownership row cannot be observed under the required transaction."""

    default_code = "CURRENT_ACCOUNT_OWNERSHIP_UNAVAILABLE"
    default_status_code = 503


@dataclass(frozen=True, slots=True)
class CurrentAccountOwnership:
    """One locked row observation, granting no ownership or execution permission.

    Row creation/update timestamps remain source facts. ``observed_at`` is the
    actual read time, never a replacement for those timestamps or historical
    account creation evidence. The observation is usable only in its reader's
    open transaction; callers must re-read on every later request.
    """

    row_pk: int
    user_id: int | None
    account_type: AccountType
    is_active: bool
    row_created_at: datetime
    row_updated_at: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        """Reject malformed identity and clocks without inventing missing owners."""

        for name in ("row_pk", "user_id"):
            value = getattr(self, name)
            if name == "user_id" and value is None:
                continue
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be an exact positive integer")
        if type(self.account_type) is not AccountType:
            raise TypeError("account_type must be an exact AccountType")
        if type(self.is_active) is not bool:
            raise TypeError("is_active must be an exact bool")
        for name in ("row_created_at", "row_updated_at", "observed_at"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not self.row_created_at <= self.row_updated_at <= self.observed_at:
            raise ValueError("live ownership row clock sequence is invalid")


class CurrentAccountOwnershipReader(Protocol):
    """Observe one physical account under the caller's same-alias transaction."""

    @property
    def database_alias(self) -> str:
        """Return the exact alias whose transaction retains the row lock."""
        ...

    def read_locked(self, *, row_pk: int) -> CurrentAccountOwnership | None:
        """Read current source facts; reject snapshots and calls outside a transaction."""
        ...
