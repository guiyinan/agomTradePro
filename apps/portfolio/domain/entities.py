"""Pure portfolio construction values and immutable plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class TargetPosition:
    """Desired portfolio weight for one security."""

    asset_code: str
    target_weight: Decimal


@dataclass(frozen=True)
class TargetPortfolio:
    """Strategy output; contains targets but never executable orders."""

    target_id: str
    decision_snapshot_id: str
    positions: tuple[TargetPosition, ...]
    target_cash_weight: Decimal
    strategy_version: str
    explanation: str = ""

    def validate(self) -> None:
        """Validate weight conservation and identifiers."""

        for field_name, value in (
            ("target_id", self.target_id),
            ("decision_snapshot_id", self.decision_snapshot_id),
            ("strategy_version", self.strategy_version),
        ):
            if not value:
                raise ValueError(f"{field_name} is required")
        codes = [item.asset_code for item in self.positions]
        if len(codes) != len(set(codes)):
            raise ValueError("target portfolio contains duplicate asset codes")
        total = self.target_cash_weight + sum(
            (item.target_weight for item in self.positions), Decimal("0")
        )
        if abs(total - Decimal("1")) > Decimal("0.000001"):
            raise ValueError("target weights and cash must sum to 1")
        if self.target_cash_weight < 0 or any(item.target_weight < 0 for item in self.positions):
            raise ValueError("target weights cannot be negative")


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Frozen account holdings used to calculate a diff."""

    snapshot_id: str
    account_id: str
    as_of_time: datetime
    cash: Decimal
    positions: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class ConstraintDecision:
    """Outcome of applying one configured trading constraint."""

    rule_code: str
    asset_code: str
    allowed: bool
    original_quantity: int
    allowed_quantity: int
    reason: str = ""


@dataclass(frozen=True)
class OrderDraft:
    """Non-executable order generated from target/current differences."""

    asset_code: str
    side: str
    quantity: int
    reference_price: Decimal
    estimated_fee: Decimal
    status: str = "DRAFT"
    remaining_quantity: int = 0
    constraints: tuple[ConstraintDecision, ...] = ()


@dataclass(frozen=True)
class TransitionPlan:
    """Immutable planning payload plus lifecycle state."""

    plan_id: str
    idempotency_key: str
    account_id: str
    decision_snapshot_id: str
    portfolio_snapshot_id: str
    target_portfolio_id: str
    as_of_time: datetime
    expires_at: datetime
    orders: tuple[OrderDraft, ...]
    constraints: tuple[ConstraintDecision, ...]
    cash_before: Decimal
    cash_after: Decimal
    status: str = "DRAFT"
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
