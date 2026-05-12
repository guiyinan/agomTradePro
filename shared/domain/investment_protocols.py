"""
Unified Investment Ledger Protocols.

Cross-module protocols shared by apps/account and apps/simulated_trading.
These define the canonical service boundary for the unified ledger so that
both API surfaces (``/api/account/*`` and ``/api/simulated-trading/*``) can
delegate to a single implementation backed by the simulated_trading models.

Pure Python — no Django / framework imports allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Value objects returned by the protocols
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LedgerPosition:
    """Unified position snapshot returned by the ledger."""

    position_id: int
    account_id: int
    asset_code: str
    asset_name: str
    shares: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    is_closed: bool
    opened_at: datetime | None
    closed_at: datetime | None
    source: str  # "manual" | "signal" | "backtest"
    source_id: int | None


@dataclass(frozen=True)
class LedgerTrade:
    """Unified trade record returned by the ledger."""

    trade_id: int
    account_id: int
    asset_code: str
    action: str  # "buy" | "sell"
    shares: float
    price: float
    amount: float
    commission: float
    realized_pnl: float
    realized_pnl_pct: float
    traded_at: datetime


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

@runtime_checkable
class InvestmentAccountRepositoryProtocol(Protocol):
    """Unified account repository."""

    def get_by_id(self, account_id: int) -> dict | None: ...

    def get_by_user(self, user_id: int, account_type: str | None = None) -> list[dict]: ...

    def save(self, account: dict) -> int: ...


@runtime_checkable
class PositionLedgerRepositoryProtocol(Protocol):
    """Unified position ledger repository."""

    def list_positions(self, account_id: int, *, include_closed: bool = False) -> list[LedgerPosition]: ...

    def get_position_by_id(self, position_id: int) -> LedgerPosition | None: ...

    def get_position(self, account_id: int, asset_code: str) -> LedgerPosition | None: ...

    def update_position(
        self,
        position_id: int,
        *,
        shares: float | None = None,
        avg_cost: float | None = None,
        current_price: float | None = None,
    ) -> LedgerPosition: ...

    def close_position(
        self,
        position_id: int,
        close_price: float | None = None,
        shares: float | None = None,
    ) -> LedgerPosition: ...

    def save(self, position: dict) -> int: ...

    def delete(self, position_id: int) -> bool: ...


@runtime_checkable
class TradeLedgerRepositoryProtocol(Protocol):
    """Unified trade ledger repository."""

    def save(self, trade: dict) -> int: ...

    def list_by_account(self, account_id: int) -> list[LedgerTrade]: ...

    def list_by_position(self, position_id: int) -> list[LedgerTrade]: ...
