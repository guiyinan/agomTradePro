"""Typed, owner-scoped resource snapshot used by read-only rebalance previews."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from apps.simulated_trading.domain.entities import Position, SimulatedAccount


@dataclass(frozen=True, slots=True)
class RebalanceExactPositionBalance:
    """Exact locked ledger quantities without a floating-point compatibility hop."""

    asset_code: str
    quantity: Decimal
    available_quantity: Decimal | None

    def __post_init__(self) -> None:
        """Preserve unknown sellable quantity and reject malformed ledger amounts."""

        if type(self.asset_code) is not str or not self.asset_code.strip():
            raise ValueError("exact balance requires an asset code")
        for value in (self.quantity, self.available_quantity):
            if value is not None and (
                type(value) is not Decimal or not value.is_finite() or value < 0
            ):
                raise ValueError("exact ledger quantities must be nonnegative Decimals")
        if self.available_quantity is not None and self.available_quantity > self.quantity:
            raise ValueError("sellable quantity exceeds the ledger position")


@dataclass(frozen=True, slots=True)
class ActiveRebalanceReservation:
    """One active order's remaining cash and share holds from the local ledger."""

    reservation_id: int
    asset_code: str
    security_id: str
    side: Literal["buy", "sell"]
    remaining_cash: Decimal
    remaining_shares: Decimal
    remaining_buy_notional: Decimal | None
    remaining_quantity: Decimal | None = None
    remaining_amount: Decimal | None = None

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
        if self.remaining_buy_notional is not None and (
            type(self.remaining_buy_notional) is not Decimal
            or not self.remaining_buy_notional.is_finite()
            or self.remaining_buy_notional < 0
        ):
            raise ValueError(
                "remaining_buy_notional must be absent or a finite nonnegative Decimal"
            )
        if self.side == "buy":
            if self.remaining_shares != Decimal("0"):
                raise ValueError("BUY reservations cannot hold shares")
        else:
            if self.remaining_shares <= Decimal("0"):
                raise ValueError("active SELL reservations must hold shares")
            if self.remaining_buy_notional is not None:
                raise ValueError("SELL reservations cannot carry BUY notional")
        if (self.remaining_quantity is None) != (self.remaining_amount is None):
            raise ValueError("capacity quantity and amount must be known together")
        if self.remaining_quantity is not None and self.remaining_amount is not None:
            if (
                type(self.remaining_quantity) is not Decimal
                or not self.remaining_quantity.is_finite()
                or self.remaining_quantity <= 0
                or type(self.remaining_amount) is not Decimal
                or not self.remaining_amount.is_finite()
                or self.remaining_amount < 0
            ):
                raise ValueError("active capacity quantity must be positive and amount nonnegative")
            if self.side == "sell" and self.remaining_quantity != self.remaining_shares:
                raise ValueError("SELL capacity quantity must equal remaining share holds")
            if self.side == "buy" and self.remaining_amount != self.remaining_buy_notional:
                raise ValueError("BUY capacity amount must equal remaining BUY notional")


@dataclass(frozen=True, slots=True)
class RebalanceResourceSnapshot:
    """One locked account, position, and active-reservation read for one owner."""

    owner_user_id: int
    read_at: datetime
    account: SimulatedAccount
    positions: tuple[Position, ...]
    active_reservations: tuple[ActiveRebalanceReservation, ...]
    exact_cash: Decimal | None = None
    exact_position_balances: tuple[RebalanceExactPositionBalance, ...] = ()
    exact_balances_complete: bool = False

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
        if type(self.exact_balances_complete) is not bool:
            raise ValueError("exact balance completeness must be explicit")
        if self.exact_cash is not None and (
            type(self.exact_cash) is not Decimal
            or not self.exact_cash.is_finite()
            or self.exact_cash < 0
        ):
            raise ValueError("exact cash must be a nonnegative Decimal or unknown")
        if type(self.exact_position_balances) is not tuple or any(
            type(row) is not RebalanceExactPositionBalance for row in self.exact_position_balances
        ):
            raise ValueError("exact balances must be a typed tuple")
        codes = [row.asset_code for row in self.exact_position_balances]
        if len(set(codes)) != len(codes):
            raise ValueError("exact balance asset codes must be unique")
        if self.exact_balances_complete and set(codes) != {
            row.asset_code for row in self.positions
        }:
            raise ValueError("complete exact balances must cover every ledger position")


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
