"""Tagged A-share, fund, bond, and commodity trading-rule evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import ClassVar, TypeAlias

from apps.portfolio.domain.optimizer_inputs import OptimizationInputKind

from ._optimization_canonical import (
    decimal_text,
    hash_components,
    require_aware,
    require_nonnegative_int,
    require_ordered_unique,
    require_positive,
    require_sha256,
    require_text,
    require_token,
    require_unit_interval,
    utc_text,
    validate_content_hash,
)
from .investable_universe import AssetMarket


@dataclass(frozen=True)
class MarketConstraintBase:
    """Shared immutable rule-version evidence for one market instrument."""

    asset_code: str
    rule_version: str
    rule_evidence_ref: str
    rule_content_hash: str
    observed_at: datetime
    available_at: datetime
    valid_until: datetime

    MARKET: ClassVar[AssetMarket]

    @property
    def market(self) -> AssetMarket:
        """Return the tagged market variant."""

        return self.MARKET

    def __post_init__(self) -> None:
        """Validate exact external rule identity and expiry."""

        require_token(self.asset_code, "asset_code")
        require_token(self.rule_version, "rule_version")
        require_text(self.rule_evidence_ref, "rule_evidence_ref")
        require_sha256(self.rule_content_hash, "rule_content_hash")
        require_aware(self.observed_at, "market rule observed_at")
        require_aware(self.available_at, "market rule available_at")
        require_aware(self.valid_until, "market rule valid_until")
        if not self.observed_at <= self.available_at < self.valid_until:
            raise ValueError("market rule availability window is invalid")

    def canonical_parts(self) -> tuple[str, ...]:
        """Return shared canonical evidence components."""

        return (
            self.market.value,
            self.asset_code,
            self.rule_version,
            self.rule_evidence_ref,
            self.rule_content_hash,
            utc_text(self.observed_at),
            utc_text(self.available_at),
            utc_text(self.valid_until),
        )


@dataclass(frozen=True)
class AShareTradingConstraint(MarketConstraintBase):
    """Explicit A-share lot, settlement, limit and capacity evidence."""

    board_lot_size: Decimal
    settlement_days: int
    minimum_order_notional: Decimal
    maximum_participation_rate: Decimal
    price_limit_rate: Decimal

    MARKET: ClassVar[AssetMarket] = AssetMarket.A_SHARE

    def __post_init__(self) -> None:
        super().__post_init__()
        require_positive(self.board_lot_size, "board_lot_size")
        require_nonnegative_int(self.settlement_days, "settlement_days")
        require_positive(self.minimum_order_notional, "minimum_order_notional")
        require_unit_interval(self.maximum_participation_rate, "maximum_participation_rate")
        require_unit_interval(self.price_limit_rate, "price_limit_rate")
        if self.maximum_participation_rate == 0 or self.price_limit_rate == 0:
            raise ValueError("A-share rate constraints must be positive")

    def canonical_parts(self) -> tuple[str, ...]:
        return (
            *super().canonical_parts(),
            decimal_text(self.board_lot_size),
            str(self.settlement_days),
            decimal_text(self.minimum_order_notional),
            decimal_text(self.maximum_participation_rate),
            decimal_text(self.price_limit_rate),
        )


@dataclass(frozen=True)
class FundTradingConstraint(MarketConstraintBase):
    """Explicit fund subscription, redemption and capacity evidence."""

    minimum_subscription_amount: Decimal
    minimum_redemption_units: Decimal
    subscription_settlement_days: int
    redemption_settlement_days: int
    maximum_daily_amount: Decimal

    MARKET: ClassVar[AssetMarket] = AssetMarket.FUND

    def __post_init__(self) -> None:
        super().__post_init__()
        require_positive(self.minimum_subscription_amount, "minimum_subscription_amount")
        require_positive(self.minimum_redemption_units, "minimum_redemption_units")
        require_nonnegative_int(
            self.subscription_settlement_days,
            "subscription_settlement_days",
        )
        require_nonnegative_int(
            self.redemption_settlement_days,
            "redemption_settlement_days",
        )
        require_positive(self.maximum_daily_amount, "maximum_daily_amount")

    def canonical_parts(self) -> tuple[str, ...]:
        return (
            *super().canonical_parts(),
            decimal_text(self.minimum_subscription_amount),
            decimal_text(self.minimum_redemption_units),
            str(self.subscription_settlement_days),
            str(self.redemption_settlement_days),
            decimal_text(self.maximum_daily_amount),
        )


@dataclass(frozen=True)
class BondTradingConstraint(MarketConstraintBase):
    """Explicit bond lot, settlement, accrued-interest and capacity evidence."""

    face_value_lot: Decimal
    settlement_days: int
    minimum_trade_notional: Decimal
    accrued_interest_required: bool
    maximum_daily_notional: Decimal

    MARKET: ClassVar[AssetMarket] = AssetMarket.BOND

    def __post_init__(self) -> None:
        super().__post_init__()
        require_positive(self.face_value_lot, "face_value_lot")
        require_nonnegative_int(self.settlement_days, "settlement_days")
        require_positive(self.minimum_trade_notional, "minimum_trade_notional")
        if not isinstance(self.accrued_interest_required, bool):
            raise ValueError("accrued_interest_required must be a boolean")
        require_positive(self.maximum_daily_notional, "maximum_daily_notional")

    def canonical_parts(self) -> tuple[str, ...]:
        return (
            *super().canonical_parts(),
            decimal_text(self.face_value_lot),
            str(self.settlement_days),
            decimal_text(self.minimum_trade_notional),
            str(self.accrued_interest_required),
            decimal_text(self.maximum_daily_notional),
        )


@dataclass(frozen=True)
class CommodityTradingConstraint(MarketConstraintBase):
    """Explicit commodity contract, margin, settlement and capacity evidence."""

    contract_multiplier: Decimal
    lot_size: Decimal
    initial_margin_rate: Decimal
    settlement_days: int
    price_limit_rate: Decimal
    maximum_daily_contracts: Decimal

    MARKET: ClassVar[AssetMarket] = AssetMarket.COMMODITY

    def __post_init__(self) -> None:
        super().__post_init__()
        require_positive(self.contract_multiplier, "contract_multiplier")
        require_positive(self.lot_size, "lot_size")
        require_unit_interval(self.initial_margin_rate, "initial_margin_rate")
        require_nonnegative_int(self.settlement_days, "settlement_days")
        require_unit_interval(self.price_limit_rate, "price_limit_rate")
        require_positive(self.maximum_daily_contracts, "maximum_daily_contracts")
        if self.initial_margin_rate == 0 or self.price_limit_rate == 0:
            raise ValueError("commodity margin and price-limit rates must be positive")

    def canonical_parts(self) -> tuple[str, ...]:
        return (
            *super().canonical_parts(),
            decimal_text(self.contract_multiplier),
            decimal_text(self.lot_size),
            decimal_text(self.initial_margin_rate),
            str(self.settlement_days),
            decimal_text(self.price_limit_rate),
            decimal_text(self.maximum_daily_contracts),
        )


MarketTradingConstraint: TypeAlias = (
    AShareTradingConstraint
    | FundTradingConstraint
    | BondTradingConstraint
    | CommodityTradingConstraint
)


@dataclass(frozen=True)
class TradingConstraintsPayload:
    """Exactly one market-tagged rule payload for every universe asset."""

    universe_hash: str
    constraints: tuple[MarketTradingConstraint, ...]
    content_hash: str

    @property
    def kind(self) -> OptimizationInputKind:
        """Return the fixed optimization input category."""

        return OptimizationInputKind.TRADING_CONSTRAINTS

    @classmethod
    def create(
        cls,
        *,
        universe_hash: str,
        constraints: tuple[MarketTradingConstraint, ...],
    ) -> TradingConstraintsPayload:
        """Sort and seal explicit rule evidence without inserting defaults."""

        ordered = tuple(sorted(constraints, key=lambda item: item.asset_code))
        return cls(
            universe_hash=universe_hash,
            constraints=ordered,
            content_hash=trading_constraints_hash(universe_hash, ordered),
        )

    def __post_init__(self) -> None:
        """Validate unique assets, runtime variants and payload digest."""

        require_sha256(self.universe_hash, "trading constraints universe_hash")
        require_ordered_unique(
            tuple(item.asset_code for item in self.constraints),
            "trading constraint assets",
        )
        expected_types: dict[AssetMarket, type[MarketConstraintBase]] = {
            AssetMarket.A_SHARE: AShareTradingConstraint,
            AssetMarket.FUND: FundTradingConstraint,
            AssetMarket.BOND: BondTradingConstraint,
            AssetMarket.COMMODITY: CommodityTradingConstraint,
        }
        for item in self.constraints:
            if type(item) is not expected_types[item.market]:
                raise ValueError("market constraint tag does not match its typed payload")
        validate_content_hash(
            self.content_hash,
            trading_constraints_hash(self.universe_hash, self.constraints),
            "trading constraints payload",
        )


def trading_constraints_hash(
    universe_hash: str,
    constraints: tuple[MarketTradingConstraint, ...],
) -> str:
    """Recompute every rule field and external rule-evidence identity."""

    return hash_components(
        "trading-constraints-payload.v1",
        universe_hash,
        *("|".join(item.canonical_parts()) for item in constraints),
    )


__all__ = [
    "AShareTradingConstraint",
    "BondTradingConstraint",
    "CommodityTradingConstraint",
    "FundTradingConstraint",
    "MarketConstraintBase",
    "MarketTradingConstraint",
    "TradingConstraintsPayload",
    "trading_constraints_hash",
]
