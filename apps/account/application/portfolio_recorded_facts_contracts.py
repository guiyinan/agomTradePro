"""Typed JSON contracts for stored Account portfolio facts.

Stored values do not establish source freshness, risk approval, an atomic
portfolio snapshot or an FX-normalized total.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, TypedDict

AccessRole = Literal["owner", "observer"]
ReadClockKind = Literal["application_read_boundary"]
StatisticsCurrencyStatus = Literal["stored_values_without_fx_normalization"]


class RecordedPositionPayload(TypedDict):
    """One stored open-position record at the JSON boundary.

    Monetary values and record clocks are explicit JSON strings.  This keeps
    Decimal precision and prevents a DRF response renderer from silently
    converting money to binary float.
    """

    id: int
    portfolio: int
    portfolio_name: str
    asset_code: str
    asset_name: str
    asset_class: str
    shares: float
    avg_cost: str
    current_price: str | None
    market_value: str
    unrealized_pnl: str
    unrealized_pnl_pct: float
    source: str
    source_id: int | None
    currency_code: str | None
    currency_name: str | None
    currency_symbol: str | None
    opened_at: str | None
    updated_at: str | None


class RecordedPositionPagePayload(TypedDict):
    """Bounded position page with an explicit total count."""

    count: int
    page: int
    page_size: int
    has_next: bool
    items: list[RecordedPositionPayload]


class RecordedReadClockPayload(TypedDict):
    """Application read boundaries, never source clocks or an atomic as-of."""

    read_started_at: str
    read_finished_at: str
    clock_kind: ReadClockKind
    source_time_status: Literal["not_provided"]


class RecordedStatisticsPayload(TypedDict):
    """Stored portfolio aggregates without currency normalization."""

    total_value: str
    total_cost: str
    total_pnl: str
    total_pnl_pct: float
    position_count: int
    asset_class_breakdown: dict[str, float]
    region_breakdown: dict[str, float]
    total_capital_inflow: str
    total_capital_outflow: str
    net_capital_flow: str
    currency_status: StatisticsCurrencyStatus


class PortfolioRecordedFactsPayload(TypedDict):
    """Complete successful JSON payload for one authorized portfolio."""

    portfolio_id: int
    portfolio_name: str
    portfolio_is_active: bool
    owner_user_id: int
    owner_username: str
    access_role: AccessRole
    positions: RecordedPositionPagePayload
    statistics: RecordedStatisticsPayload
    position_read_clock: RecordedReadClockPayload
    statistics_read_clock: RecordedReadClockPayload


@dataclass(frozen=True, slots=True)
class RecordedReadClock:
    """Record one application read interval without calling it a source time."""

    read_started_at: datetime
    read_finished_at: datetime

    def to_payload(self) -> RecordedReadClockPayload:
        """Return the JSON-safe clock metadata for this read interval."""

        return {
            "read_started_at": self.read_started_at.isoformat(),
            "read_finished_at": self.read_finished_at.isoformat(),
            "clock_kind": "application_read_boundary",
            "source_time_status": "not_provided",
        }


@dataclass(frozen=True, slots=True)
class RecordedPosition:
    """Typed stored position projection preserving native values and nulls."""

    id: int
    portfolio: int
    portfolio_name: str
    asset_code: str
    asset_name: str
    asset_class: str
    shares: float
    avg_cost: Decimal
    current_price: Decimal | None
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: float
    source: str
    source_id: int | None
    currency_code: str | None
    currency_name: str | None
    currency_symbol: str | None
    opened_at: datetime | None
    updated_at: datetime | None

    def to_payload(self) -> RecordedPositionPayload:
        """Return the stored position with explicit JSON scalar encoding."""

        return {
            "id": self.id,
            "portfolio": self.portfolio,
            "portfolio_name": self.portfolio_name,
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "asset_class": self.asset_class,
            "shares": self.shares,
            "avg_cost": str(self.avg_cost),
            "current_price": (str(self.current_price) if self.current_price is not None else None),
            "market_value": str(self.market_value),
            "unrealized_pnl": str(self.unrealized_pnl),
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "source": self.source,
            "source_id": self.source_id,
            "currency_code": self.currency_code,
            "currency_name": self.currency_name,
            "currency_symbol": self.currency_symbol,
            "opened_at": (self.opened_at.isoformat() if self.opened_at is not None else None),
            "updated_at": (self.updated_at.isoformat() if self.updated_at is not None else None),
        }


@dataclass(frozen=True, slots=True)
class RecordedPositionPage:
    """Bounded page over all stored open-position rows returned by the port."""

    count: int
    page: int
    page_size: int
    has_next: bool
    items: tuple[RecordedPosition, ...]

    def to_payload(self) -> RecordedPositionPagePayload:
        """Return count and pagination metadata without silent truncation."""

        return {
            "count": self.count,
            "page": self.page,
            "page_size": self.page_size,
            "has_next": self.has_next,
            "items": [item.to_payload() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class RecordedStatistics:
    """Stored aggregate values whose currency basis remains unqualified."""

    total_value: Decimal
    total_cost: Decimal
    total_pnl: Decimal
    total_pnl_pct: float
    position_count: int
    asset_class_breakdown: dict[str, float]
    region_breakdown: dict[str, float]
    total_capital_inflow: Decimal
    total_capital_outflow: Decimal
    net_capital_flow: Decimal

    def to_payload(self) -> RecordedStatisticsPayload:
        """Return aggregates with an explicit no-FX-normalization status."""

        return {
            "total_value": str(self.total_value),
            "total_cost": str(self.total_cost),
            "total_pnl": str(self.total_pnl),
            "total_pnl_pct": self.total_pnl_pct,
            "position_count": self.position_count,
            "asset_class_breakdown": dict(self.asset_class_breakdown),
            "region_breakdown": dict(self.region_breakdown),
            "total_capital_inflow": str(self.total_capital_inflow),
            "total_capital_outflow": str(self.total_capital_outflow),
            "net_capital_flow": str(self.net_capital_flow),
            "currency_status": "stored_values_without_fx_normalization",
        }


__all__ = [
    "AccessRole",
    "PortfolioRecordedFactsPayload",
    "RecordedPosition",
    "RecordedPositionPage",
    "RecordedPositionPagePayload",
    "RecordedPositionPayload",
    "RecordedReadClock",
    "RecordedReadClockPayload",
    "RecordedStatistics",
    "RecordedStatisticsPayload",
]
