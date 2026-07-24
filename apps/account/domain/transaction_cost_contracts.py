"""Typed transaction-cost contracts shared across account layers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import NotRequired, Protocol, TypedDict


class AssetMetadataRecord(TypedDict):
    """Asset metadata fields required by transaction-cost estimation."""

    asset_code: str
    name: str
    asset_class: str
    region: str
    cross_border: str
    style: str


class TransactionCostConfigRecord(TypedDict):
    """Normalized configuration used to calculate transaction costs."""

    id: NotRequired[int]
    market: str
    asset_class: str
    commission_rate: Decimal
    slippage_rate: Decimal
    stamp_duty_rate: Decimal
    transfer_fee_rate: Decimal
    min_commission: Decimal
    cost_warning_threshold: float


class TransactionCostRecord(TypedDict):
    """Transaction fields required by cost recording and analysis."""

    id: int
    portfolio_id: int
    position_id: int | None
    asset_code: str
    action: str
    notional: Decimal
    commission: Decimal
    slippage: Decimal | None
    stamp_duty: Decimal | None
    transfer_fee: Decimal | None
    estimated_cost: Decimal | None
    cost_variance: Decimal | None
    cost_variance_pct: float | None
    traded_at: datetime


class HighCostTransaction(TypedDict):
    """Serialized high-cost transaction returned by the analysis use case."""

    id: int
    asset_code: str
    action: str
    notional: float
    cost_ratio: float
    traded_at: datetime


class AssetMetadataLookupProtocol(Protocol):
    """Read the asset metadata needed by transaction-cost estimation."""

    def get_asset_by_code(self, asset_code: str) -> AssetMetadataRecord | None:
        """Return metadata for ``asset_code`` when it exists."""

        ...


class TransactionCostConfigRepositoryProtocol(Protocol):
    """Read explicit transaction-cost configuration."""

    def get_cost_config(self, market: str, asset_class: str) -> TransactionCostConfigRecord | None:
        """Return the active configuration for a market and asset class."""

        ...


class TransactionCostRepositoryProtocol(Protocol):
    """Persist and query transaction-cost records."""

    def update_transaction_costs(
        self,
        transaction_id: int,
        *,
        commission: Decimal,
        slippage: Decimal | None = None,
        stamp_duty: Decimal | None = None,
        transfer_fee: Decimal | None = None,
    ) -> TransactionCostRecord | None:
        """Update actual costs and return the refreshed transaction record."""

        ...

    def list_user_transaction_costs(
        self,
        user_id: int,
        *,
        portfolio_id: int | None = None,
        since_date: datetime | None = None,
    ) -> list[TransactionCostRecord]:
        """Return transaction-cost records for the requested analysis scope."""

        ...
