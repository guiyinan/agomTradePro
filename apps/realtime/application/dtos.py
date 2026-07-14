"""Realtime application DTOs."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from apps.realtime.domain.entities import PriceAlert, PriceSubscription, RealtimePrice


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


@dataclass(frozen=True)
class PriceAlertDTO:
    """Serializable durable price-alert payload."""

    id: int
    asset_code: str
    condition: str
    threshold: Decimal
    status: str
    message: str
    triggered_price: Decimal | None
    triggered_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_domain(cls, alert: PriceAlert) -> "PriceAlertDTO":
        """Build an alert DTO from its domain value."""

        if alert.id is None:
            raise ValueError("persisted alert must have an id")
        return cls(
            id=alert.id,
            asset_code=alert.asset_code,
            condition=alert.condition.value,
            threshold=alert.threshold,
            status=alert.status.value,
            message=alert.message,
            triggered_price=alert.triggered_price,
            triggered_at=alert.triggered_at,
            created_at=alert.created_at,
            updated_at=alert.updated_at,
        )


@dataclass(frozen=True)
class PriceSubscriptionDTO:
    """Serializable realtime subscription payload."""

    id: int
    asset_code: str
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_domain(
        cls,
        subscription: PriceSubscription,
    ) -> "PriceSubscriptionDTO":
        """Build a subscription DTO from its domain value."""

        if subscription.id is None:
            raise ValueError("persisted subscription must have an id")
        return cls(
            id=subscription.id,
            asset_code=subscription.asset_code,
            is_active=subscription.is_active,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
        )
