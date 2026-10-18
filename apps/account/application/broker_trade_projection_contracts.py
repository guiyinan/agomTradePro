"""Account-owned contracts for the broker-fact projection capability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

BrokerProjectionAction = Literal["buy", "sell"]
BrokerPositionMapState = Literal["valid", "missing", "ambiguous", "mismatch"]


@dataclass(frozen=True, slots=True)
class BrokerUnifiedPositionSnapshot:
    """Narrow owner-scoped balance and source-map snapshot."""

    owner_user_id: int
    portfolio_id: int
    asset_code: str
    account_id: int | None
    account_mapping_id: int | None
    account_mapping_count: int
    unified_position_id: int | None
    position_map_source_id: int | None
    position_map_target_id: int | None
    position_map_state: BrokerPositionMapState
    total_shares: Decimal | None
    available_quantity: Decimal | None
    available_quantity_known: bool | None
    average_cost: Decimal | None
    reference_mark: Decimal | None
    valuation_known: bool | None
    source_updated_at: datetime | None
    first_buy_date: date | None
    first_buy_date_known: bool | None
    asset_name: str | None
    asset_type: str | None
    blocked_reason_code: str | None


@dataclass(frozen=True, slots=True)
class BrokerLegacyPositionSeed:
    """Exact Account position values needed to reconcile one broker fact."""

    source_position_id: int
    asset_code: str
    asset_name: str
    asset_type: str
    total_shares: Decimal
    average_cost: Decimal
    reference_mark: Decimal | None
    valuation_known: bool
    first_buy_date: date


@dataclass(frozen=True, slots=True)
class BrokerPositionExpectation:
    """Identity and economics observed before one position update."""

    account_id: int | None
    account_mapping_id: int | None
    account_mapping_count: int
    unified_position_id: int | None
    position_map_source_id: int | None
    position_map_target_id: int | None
    total_shares: Decimal | None
    average_cost: Decimal | None
    reference_mark: Decimal | None
    valuation_known: bool | None
    available_quantity: Decimal | None
    available_quantity_known: bool | None
    asset_type: str | None
    position_map_state: BrokerPositionMapState


@dataclass(frozen=True, slots=True)
class BrokerActualFact:
    """Persisted Account transaction values for one mirror-trade request."""

    transaction_id: int
    asset_code: str
    asset_name: str
    asset_type: str
    action: BrokerProjectionAction
    shares: Decimal
    price: Decimal
    notional: Decimal
    commission: Decimal
    commission_known: bool
    stamp_duty: Decimal
    stamp_duty_known: bool
    transfer_fee: Decimal
    transfer_fee_known: bool
    slippage: Decimal
    slippage_known: bool
    traded_at: datetime


@dataclass(frozen=True, slots=True)
class BrokerTradeProjectionCommand:
    """Request one locked, source-mapped actual-fact projection."""

    owner_user_id: int
    portfolio_id: int
    portfolio_name: str
    portfolio_is_active: bool
    legacy_position: BrokerLegacyPositionSeed | None
    expectation: BrokerPositionExpectation
    fact: BrokerActualFact


@dataclass(frozen=True, slots=True)
class BrokerTradeProjectionResult:
    """Outcome and resulting position values for one projection attempt."""

    applied: bool
    already_applied: bool
    account_id: int | None
    unified_position_id: int | None
    simulated_trade_id: int | None
    total_shares: Decimal | None
    average_cost: Decimal | None
    reference_mark: Decimal | None
    available_quantity_known: bool | None
    fully_closed: bool
    reason_code: str | None


class BrokerTradeProjectionRepository(Protocol):
    """Infrastructure port used by Simulated Trading's projection service."""

    def get_existing_real_account_id(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
    ) -> int | None:
        """Resolve one existing, exact owner-scoped real-account mapping."""
        ...

    def capture_position_snapshots(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        portfolio_name: str,
        asset_codes: tuple[str, ...],
        legacy_position_ids: Mapping[str, int | None],
    ) -> tuple[BrokerUnifiedPositionSnapshot, ...]:
        """Read balances and source-map identities without creating ledger rows."""
        ...

    def apply_actual_broker_fact(
        self,
        command: BrokerTradeProjectionCommand,
    ) -> BrokerTradeProjectionResult:
        """Apply one actual execution, position mutation, and source-map write."""
        ...

    def bind_legacy_position_source(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        source_position_id: int,
        unified_position_id: int,
    ) -> bool:
        """Bind a newly created Account position to its exact unified row."""
        ...


class BrokerTradeProjectionGateway(Protocol):
    """Account-owned consumer port for broker projection capabilities."""

    def get_existing_real_account_id(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
    ) -> int | None:
        """Resolve an existing exact real account without provisioning one."""
        ...

    def capture_position_snapshots(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        portfolio_name: str,
        asset_codes: tuple[str, ...],
        legacy_position_ids: Mapping[str, int | None],
    ) -> tuple[BrokerUnifiedPositionSnapshot, ...]:
        """Read position balances and mappings for reconciliation preview."""
        ...

    def apply_actual_broker_fact(
        self,
        command: BrokerTradeProjectionCommand,
    ) -> BrokerTradeProjectionResult:
        """Apply one imported execution as an actual-fact projection."""
        ...

    def bind_legacy_position_source(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        source_position_id: int,
        unified_position_id: int,
    ) -> bool:
        """Bind one newly created Account position to the unified position."""
        ...


__all__ = [
    "BrokerActualFact",
    "BrokerLegacyPositionSeed",
    "BrokerPositionExpectation",
    "BrokerPositionMapState",
    "BrokerProjectionAction",
    "BrokerTradeProjectionCommand",
    "BrokerTradeProjectionGateway",
    "BrokerTradeProjectionRepository",
    "BrokerTradeProjectionResult",
    "BrokerUnifiedPositionSnapshot",
]
