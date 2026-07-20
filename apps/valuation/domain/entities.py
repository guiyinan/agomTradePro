"""Canonical valuation entities."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4


class ValuationMethod(Enum):
    """Supported valuation methods."""

    DCF = "DCF"
    PE_BAND = "PE_BAND"
    PB_BAND = "PB_BAND"
    PEG = "PEG"
    DIVIDEND = "DIVIDEND"
    COMPOSITE = "COMPOSITE"
    FALLBACK = "FALLBACK"


@dataclass(frozen=True)
class ValuationSnapshot:
    """Immutable point-in-time valuation contract."""

    snapshot_id: str
    security_code: str
    valuation_method: str
    fair_value: Decimal
    entry_price_low: Decimal
    entry_price_high: Decimal
    target_price_low: Decimal
    target_price_high: Decimal
    stop_loss_price: Decimal
    calculated_at: datetime
    input_parameters: dict[str, Any]
    version: int = 1
    is_legacy: bool = False

    @property
    def entry_range(self) -> tuple[Decimal, Decimal]:
        """Return the inclusive entry-price range."""
        return (self.entry_price_low, self.entry_price_high)

    @property
    def target_range(self) -> tuple[Decimal, Decimal]:
        """Return the target-price range."""
        return (self.target_price_low, self.target_price_high)

    @property
    def upside_potential(self) -> Decimal:
        """Return percentage upside from the entry midpoint."""
        entry_mid = (self.entry_price_low + self.entry_price_high) / 2
        target_mid = (self.target_price_low + self.target_price_high) / 2
        if entry_mid <= 0:
            return Decimal("0")
        return (target_mid - entry_mid) / entry_mid * 100

    @property
    def downside_risk(self) -> Decimal:
        """Return percentage downside from the entry midpoint to stop loss."""
        entry_mid = (self.entry_price_low + self.entry_price_high) / 2
        if entry_mid <= 0:
            return Decimal("0")
        return (entry_mid - self.stop_loss_price) / entry_mid * 100

    @property
    def risk_reward_ratio(self) -> Decimal:
        """Return upside divided by downside risk."""
        if self.downside_risk <= 0:
            return Decimal("0")
        return self.upside_potential / self.downside_risk

    def is_price_in_entry_range(self, price: Decimal) -> bool:
        """Return whether price is inside the entry range."""
        return self.entry_price_low <= price <= self.entry_price_high

    def is_price_above_target(self, price: Decimal) -> bool:
        """Return whether price reached the lower target."""
        return price >= self.target_price_low

    def should_stop_loss(self, price: Decimal) -> bool:
        """Return whether price reached the stop-loss threshold."""
        return price <= self.stop_loss_price

    def to_dict(self) -> dict[str, Any]:
        """Serialize the snapshot into an audit-safe mapping."""
        return {
            "snapshot_id": self.snapshot_id,
            "security_code": self.security_code,
            "valuation_method": self.valuation_method,
            "fair_value": str(self.fair_value),
            "entry_price_low": str(self.entry_price_low),
            "entry_price_high": str(self.entry_price_high),
            "target_price_low": str(self.target_price_low),
            "target_price_high": str(self.target_price_high),
            "stop_loss_price": str(self.stop_loss_price),
            "calculated_at": self.calculated_at.isoformat(),
            "input_parameters": self.input_parameters,
            "version": self.version,
            "is_legacy": self.is_legacy,
            "upside_potential": str(self.upside_potential),
            "downside_risk": str(self.downside_risk),
            "risk_reward_ratio": str(self.risk_reward_ratio),
        }


def create_valuation_snapshot(
    security_code: str,
    valuation_method: str,
    fair_value: Decimal,
    entry_price_low: Decimal,
    entry_price_high: Decimal,
    target_price_low: Decimal,
    target_price_high: Decimal,
    stop_loss_price: Decimal,
    input_parameters: dict[str, Any],
    is_legacy: bool = False,
) -> ValuationSnapshot:
    """Create an immutable, timezone-aware valuation snapshot."""
    return ValuationSnapshot(
        snapshot_id=f"vs_{uuid4().hex[:12]}",
        security_code=security_code,
        valuation_method=valuation_method,
        fair_value=fair_value,
        entry_price_low=entry_price_low,
        entry_price_high=entry_price_high,
        target_price_low=target_price_low,
        target_price_high=target_price_high,
        stop_loss_price=stop_loss_price,
        calculated_at=datetime.now(UTC),
        input_parameters=input_parameters,
        is_legacy=is_legacy,
    )
