"""Realtime application DTOs."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from apps.realtime.domain.entities import RealtimePrice


@dataclass(frozen=True)
class RealtimePriceDTO:
    """Serializable realtime price payload."""

    asset_code: str
    asset_type: str
    price: Decimal
    change: Decimal | None
    change_pct: Decimal | None
    volume: int | None
    timestamp: datetime
    source: str

    @classmethod
    def from_domain(cls, price: RealtimePrice) -> "RealtimePriceDTO":
        """Build a DTO from a realtime price entity."""
        return cls(
            asset_code=price.asset_code,
            asset_type=price.asset_type.value,
            price=price.price,
            change=price.change,
            change_pct=price.change_pct,
            volume=price.volume,
            timestamp=price.timestamp,
            source=price.source,
        )
