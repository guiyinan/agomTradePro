"""Typed transaction-record contracts for the fee-availability candidate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class CreateTransactionInput:
    """Validated user input for one ordinary account transaction."""

    actor_user_id: int
    portfolio_id: int
    position_id: int | None
    action: str
    asset_code: str
    shares: float
    price: Decimal
    notes: str
    traded_at: datetime
    commission: Decimal | None = None
    slippage: Decimal | None = None
    stamp_duty: Decimal | None = None
    transfer_fee: Decimal | None = None


@dataclass(frozen=True)
class NewTransactionRecord:
    """Application-normalized transaction fields ready for persistence."""

    actor_user_id: int
    portfolio_id: int
    position_id: int | None
    action: str
    asset_code: str
    shares: float
    price: Decimal
    notional: Decimal
    notes: str
    traded_at: datetime
    commission: Decimal | None
    slippage: Decimal | None
    stamp_duty: Decimal | None
    transfer_fee: Decimal | None


@dataclass(frozen=True)
class TransactionRecord:
    """Canonical output for create, list, detail, and Admin identity binding."""

    id: int
    portfolio_id: int
    portfolio_name: str
    position_id: int | None
    asset_code: str
    action: str
    shares: float
    price: Decimal
    notional: Decimal
    commission: Decimal | None
    commission_known: bool | None
    slippage: Decimal | None
    slippage_known: bool | None
    stamp_duty: Decimal | None
    stamp_duty_known: bool | None
    transfer_fee: Decimal | None
    transfer_fee_known: bool | None
    broker_name: str
    external_trade_id: str
    broker_trade_key: str | None
    import_batch_id: int | None
    notes: str
    traded_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class TransactionPage:
    """One owner-scoped page using the existing count/order contract."""

    count: int
    page_number: int
    page_size: int
    results: tuple[TransactionRecord, ...]


class TransactionRecordRepositoryProtocol(Protocol):
    """Persistence boundary for account transaction records."""

    def create_transaction(self, record: NewTransactionRecord) -> TransactionRecord:
        """Create after rechecking portfolio and position ownership."""

        ...

    def list_user_transactions(
        self,
        user_id: int,
        *,
        page_number: int,
        page_size: int,
    ) -> TransactionPage:
        """Return one owner-scoped page ordered by descending traded time."""

        ...

    def get_user_transaction(
        self,
        user_id: int,
        transaction_id: int,
    ) -> TransactionRecord | None:
        """Return an owner-scoped transaction or None for missing/foreign rows."""

        ...
