"""Transport-independent contracts for the integrated QMT bridge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class BridgeSample:
    """One unadjusted source observation; volume remains in source units."""

    asset_code: str
    observed_at: datetime
    price: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    prev_close: Decimal | None = None
    volume: Decimal | None = None
    amount: Decimal | None = None
    bar_date: date | None = None

    def validate(self) -> None:
        """Reject malformed facts regardless of the calling transport."""
        if not self.asset_code or self.observed_at.utcoffset() is None:
            raise ValueError("A canonical asset and timezone-aware observation are required")
        values = (self.price, self.open, self.high, self.low, self.prev_close)
        if any(value is not None and (not value.is_finite() or value <= 0) for value in values):
            raise ValueError("Prices must be positive finite numbers")
        for value in (self.volume, self.amount):
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError("Volume and amount must be nonnegative finite numbers")
        if self.bar_date is not None and any(v is None for v in (self.open, self.high, self.low)):
            raise ValueError("Daily bars require complete OHLC")
        if self.high is not None and self.low is not None:
            if self.high < self.low or not self.low <= self.price <= self.high:
                raise ValueError("OHLC values are inconsistent")
            if self.open is not None and not self.low <= self.open <= self.high:
                raise ValueError("Open price is outside the bar range")


@dataclass(frozen=True)
class BridgeBatch:
    """An immutable upload retried under the same batch identity."""

    batch_id: str
    kind: str
    collected_at: datetime
    samples: tuple[BridgeSample, ...]

    def validate(self, now: datetime) -> None:
        """Validate batch boundaries before any write, including non-HTTP callers."""
        UUID(self.batch_id)
        if self.kind not in ("quote", "bar") or not 1 <= len(self.samples) <= 500:
            raise ValueError("Upload requires 1–500 quote or daily bar records")
        if self.collected_at.utcoffset() is None or self.collected_at > now:
            raise ValueError("Collection time must be timezone-aware and not in the future")
        keys: set[tuple[str, datetime, date | None]] = set()
        for sample in self.samples:
            sample.validate()
            if sample.observed_at > self.collected_at:
                raise ValueError("Observation time cannot follow collection time")
            if (sample.bar_date is not None) != (self.kind == "bar"):
                raise ValueError("Record kind does not match batch kind")
            if sample.bar_date is not None and sample.observed_at.date() != sample.bar_date:
                raise ValueError("Daily observation date does not match its bar date")
            key = (sample.asset_code, sample.observed_at, sample.bar_date)
            if key in keys:
                raise ValueError("Duplicate record in batch")
            keys.add(key)
