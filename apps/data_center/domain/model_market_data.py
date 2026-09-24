"""Provider-neutral raw daily inputs; stock prices in CNY, indices in points, volume shares."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ModelDailyBar:
    """One source observation, with a multiplicative corporate-action factor."""

    asset_code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    change_percent: float
    adjustment_factor: float | None
    source: str
    amount: float | None = None


@dataclass(frozen=True)
class TradingCalendarEvidence:
    """Source-bound proof that a provider answered one complete calendar window."""

    coverage_start: date
    coverage_end: date
    open_sessions: tuple[date, ...]
    source: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.coverage_start > self.coverage_end:
            raise ValueError("trading calendar coverage is inverted")
        if not self.source.strip():
            raise ValueError("trading calendar source is required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("trading calendar observed_at must be timezone-aware")
        if tuple(sorted(set(self.open_sessions))) != self.open_sessions:
            raise ValueError("trading calendar sessions must be sorted and unique")
        if any(
            session < self.coverage_start or session > self.coverage_end
            for session in self.open_sessions
        ):
            raise ValueError("trading calendar session falls outside coverage")


@runtime_checkable
class TradingCalendarEvidencePort(Protocol):
    """Expose source and coverage with exchange-calendar observations."""

    def trading_calendar_evidence(
        self, start_date: date, end_date: date
    ) -> TradingCalendarEvidence:
        """Return explicit source and coverage for a bounded calendar query."""
        ...


@runtime_checkable
class ModelHistoryPreparationPort(Protocol):
    """Optional bounded prefetch that preserves the per-asset history contract."""

    def prepare_stock_history(
        self, asset_codes: tuple[str, ...], start_date: date, end_date: date
    ) -> None:
        """Prepare exact-window inputs without publishing or changing routing semantics."""
        ...


@runtime_checkable
class ModelSuspensionPort(Protocol):
    """Optional evidence for full-day suspensions, never inferred from missing bars."""

    def suspended_days(self, asset_code: str, start_date: date, end_date: date) -> tuple[date, ...]:
        """Return explicitly observed full-day suspension dates for this asset."""
        ...


class ModelMarketDataPort(Protocol):
    """Historical inputs required by model builders and price consumers."""

    def stock_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Return raw prices and same-source factors, preserving observation dates."""
        ...

    def index_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Return unadjusted index history."""
        ...

    def trade_days(self, start_date: date, end_date: date) -> tuple[date, ...]:
        """Return observed exchange calendar dates in the requested window."""
        ...

    def index_members(self, index_code: str, target_date: date) -> tuple[str, ...]:
        """Return constituents effective at or before the target date."""
        ...
