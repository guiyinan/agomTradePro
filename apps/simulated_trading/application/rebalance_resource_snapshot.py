"""Typed, owner-scoped resource snapshot used by read-only rebalance previews."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from apps.simulated_trading.domain.entities import Position, SimulatedAccount


@dataclass(frozen=True, slots=True)
class ActiveRebalanceReservation:
    """One active order's remaining cash and share holds from the local ledger."""

    reservation_id: int
    asset_code: str
    security_id: str
    side: Literal["buy", "sell"]
    remaining_cash: Decimal
    remaining_shares: Decimal

    def __post_init__(self) -> None:
        """Reject incomplete or non-finite held-resource evidence."""

        if type(self.reservation_id) is not int or self.reservation_id <= 0:
            raise ValueError("reservation_id must be a positive integer")
        if type(self.asset_code) is not str or not self.asset_code.strip():
            raise ValueError("asset_code must be a nonempty string")
        if type(self.security_id) is not str or not self.security_id.strip():
            raise ValueError("security_id must be a nonempty string")
        if self.side not in {"buy", "sell"}:
            raise ValueError("reservation side is unsupported")
        if (
            type(self.remaining_cash) is not Decimal
            or not self.remaining_cash.is_finite()
            or self.remaining_cash < 0
        ):
            raise ValueError("remaining_cash must be a finite nonnegative Decimal")
        if (
            type(self.remaining_shares) is not Decimal
            or not self.remaining_shares.is_finite()
            or self.remaining_shares < 0
        ):
            raise ValueError("remaining_shares must be a finite nonnegative Decimal")
        if self.side == "buy" and self.remaining_shares != Decimal("0"):
            raise ValueError("BUY reservations cannot hold shares")
        if self.side == "sell" and self.remaining_shares <= Decimal("0"):
            raise ValueError("active SELL reservations must hold shares")


@dataclass(frozen=True, slots=True)
class RebalanceResourceSnapshot:
    """One locked account, position, and active-reservation read for one owner."""

    owner_user_id: int
    read_at: datetime
    account: SimulatedAccount
    positions: tuple[Position, ...]
    active_reservations: tuple[ActiveRebalanceReservation, ...]

    def __post_init__(self) -> None:
        """Validate the typed outer snapshot before application use."""

        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be a positive integer")
        if (
            type(self.read_at) is not datetime
            or self.read_at.tzinfo is None
            or self.read_at.utcoffset() is None
        ):
            raise ValueError("read_at must be an aware local ledger-read time")
        if type(self.account) is not SimulatedAccount:
            raise ValueError("account must be a SimulatedAccount")
        if type(self.positions) is not tuple or any(
            type(position) is not Position for position in self.positions
        ):
            raise ValueError("positions must be a tuple of Position entities")
        if type(self.active_reservations) is not tuple or any(
            type(row) is not ActiveRebalanceReservation for row in self.active_reservations
        ):
            raise ValueError("active_reservations must be a typed tuple")
        if any(position.account_id != self.account.account_id for position in self.positions):
            raise ValueError("position account ids must match the snapshot account")


class RebalanceResourceSnapshotReader(Protocol):
    """Read one owner-scoped resource snapshot under the established ledger locks."""

    def read_account_snapshot(
        self,
        *,
        account_id: int,
        user_id: int,
    ) -> RebalanceResourceSnapshot | None:
        """Return the exact locked account, position, and active-hold evidence."""


__all__: tuple[str, ...] = (
    "ActiveRebalanceReservation",
    "RebalanceResourceSnapshot",
    "RebalanceResourceSnapshotReader",
)
