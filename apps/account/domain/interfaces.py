"""
Account Domain Interfaces

Repository protocols for the account module.
These protocols define the contracts that infrastructure layer must implement.
Application layer should depend on these protocols, not concrete implementations.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from apps.account.domain.entities import (
    AccountProfile,
    PortfolioSnapshot,
    Position,
    Transaction,
)


class AccountRepositoryProtocol(Protocol):
    """Account repository protocol for user account operations."""

    def get_by_user_id(self, user_id: int) -> AccountProfile | None:
        """Get account profile by user ID."""
        ...

    def create_default_profile(self, user_id: int) -> AccountProfile:
        """Create default profile for user."""
        ...

    def get_or_create_default_portfolio(self, user_id: int) -> int:
        """Get or create default portfolio, returns portfolio_id."""
        ...

    def get_account_profile_with_volatility_config(
        self, user_id: int
    ) -> dict[str, Any] | None:
        """
        Get account profile with volatility configuration.

        Returns:
            Dict with keys: user_id, target_volatility, volatility_tolerance,
            max_volatility_reduction, or None if not found
        """
        ...


class PortfolioRepositoryProtocol(Protocol):
    """Portfolio repository protocol for portfolio operations."""

    def get_user_portfolios(self, user_id: int) -> list[dict]:
        """Get all portfolios for a user."""
        ...

    def get_portfolio_snapshot(self, portfolio_id: int) -> PortfolioSnapshot | None:
        """Get portfolio snapshot with positions."""
        ...

    def get_active_portfolios(self, user_id: int | None = None) -> list[dict]:
        """
        Get active portfolios.

        Args:
            user_id: Optional user ID to filter by

        Returns:
            List of portfolio dicts with id, user_id, name
        """
        ...


class PositionRepositoryProtocol(Protocol):
    """Position repository protocol for position operations."""

    def get_user_positions(
        self,
        user_id: int,
        status: str | None = None,
        asset_class: str | None = None,
    ) -> list[Position]:
        """Get user positions with optional filters."""
        ...

    def get_position_by_id(self, position_id: int) -> Position | None:
        """Get position by ID."""
        ...

    def create_position(
        self,
        portfolio_id: int,
        asset_code: str,
        shares: float,
        price: Decimal,
        source: str = "manual",
        source_id: int | None = None,
    ) -> Position:
        """Create a new position."""
        ...

    def close_position(
        self,
        position_id: int,
        shares: float | None = None,
        price: Decimal | None = None,
        reason: str | None = None,
    ) -> Position | None:
        """Close position (full or partial)."""
        ...

    def update_position_price(
        self, position_id: int, new_price: Decimal
    ) -> Position | None:
        """Update position current price and recalculate P&L."""
        ...

    def get_active_positions_by_portfolio(self, portfolio_id: int) -> list[Position]:
        """Get all active positions for a portfolio."""
        ...

    def get_position_with_user_email(
        self, position_id: int
    ) -> dict[str, Any] | None:
        """
        Get position with user email for notifications.

        Returns:
            Dict with position info and user_email, or None
        """
        ...


class TransactionRepositoryProtocol(Protocol):
    """Transaction repository protocol for transaction operations."""

    def get_portfolio_transactions(
        self,
        portfolio_id: int,
        limit: int = 50,
    ) -> list[Transaction]:
        """Get portfolio transactions."""
        ...

    def get_transaction_by_id(self, transaction_id: int) -> dict[str, Any] | None:
        """
        Get transaction by ID.

        Returns:
            Transaction dict with all fields, or None
        """
        ...

    def update_transaction_costs(
        self,
        transaction_id: int,
        commission: Decimal,
        slippage: Decimal | None = None,
        stamp_duty: Decimal | None = None,
        transfer_fee: Decimal | None = None,
        estimated_cost: Decimal | None = None,
    ) -> bool:
        """Update transaction cost fields."""
        ...

    def get_user_transactions_for_analysis(
        self,
        user_id: int,
        portfolio_id: int | None = None,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """
        Get user transactions for cost analysis.

        Returns:
            List of transaction dicts with cost fields
        """
        ...


class AssetMetadataRepositoryProtocol(Protocol):
    """Asset metadata repository protocol."""

    def get_or_create_asset(
        self,
        asset_code: str,
        name: str,
        asset_class: str = "equity",
        region: str = "CN",
        **kwargs
    ) -> dict:
        """Get or create asset metadata."""
        ...

    def get_asset_by_code(self, asset_code: str) -> dict[str, Any] | None:
        """
        Get asset metadata by code.

        Returns:
            Dict with asset_class, region, etc., or None
        """
        ...

    def search_assets(
        self,
        query: str,
        asset_class: str | None = None,
        region: str | None = None,
    ) -> list[dict]:
        """Search assets."""
        ...


class StopLossRepositoryProtocol(Protocol):
    """Stop loss repository protocol for stop loss configuration operations."""

    def get_active_stop_loss_configs(
        self, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Get all active stop loss configurations.

        Args:
            user_id: Optional user ID to filter by

        Returns:
            List of stop loss config dicts with position relationship
        """
        ...

    def get_stop_loss_config_by_position(
        self, position_id: int
    ) -> dict[str, Any] | None:
        """Get stop loss config for a position."""
        ...

    def create_stop_loss_config(
        self,
        position_id: int,
        stop_loss_type: str,
        stop_loss_pct: float,
        trailing_stop_pct: float | None = None,
        max_holding_days: int | None = None,
        highest_price: Decimal | None = None,
    ) -> dict[str, Any]:
        """Create stop loss configuration."""
        ...

    def update_stop_loss_config(
        self,
        config_id: int,
        status: str | None = None,
        highest_price: Decimal | None = None,
        highest_price_updated_at: Any | None = None,
        triggered_at: Any | None = None,
    ) -> bool:
        """Update stop loss configuration."""
        ...

    def create_stop_loss_trigger(
        self,
        position_id: int,
        trigger_type: str,
        trigger_price: Decimal,
        trigger_reason: str,
        pnl: Decimal,
        pnl_pct: float,
        notes: str = "",
    ) -> dict[str, Any]:
        """Create stop loss trigger record."""
        ...


class TakeProfitRepositoryProtocol(Protocol):
    """Take profit repository protocol for take profit configuration operations."""

    def get_active_take_profit_configs(
        self, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Get all active take profit configurations.

        Args:
            user_id: Optional user ID to filter by

        Returns:
            List of take profit config dicts with position relationship
        """
        ...

    def get_take_profit_config_by_position(
        self, position_id: int
    ) -> dict[str, Any] | None:
        """Get take profit config for a position."""
        ...

    def create_take_profit_config(
        self,
        position_id: int,
        take_profit_pct: float,
        partial_profit_levels: list[float] | None = None,
    ) -> dict[str, Any]:
        """Create take profit configuration."""
        ...

    def update_take_profit_config(
        self,
        config_id: int,
        is_active: bool | None = None,
    ) -> bool:
        """Update take profit configuration."""
        ...


class PortfolioSnapshotRepositoryProtocol(Protocol):
    """Portfolio snapshot repository protocol for historical data."""

    def get_snapshots_for_volatility(
        self,
        portfolio_id: int,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """
        Get portfolio daily snapshots for volatility calculation.

        Returns:
            List of dicts with snapshot_date, total_value
        """
        ...


class TransactionCostConfigRepositoryProtocol(Protocol):
    """Transaction cost configuration repository protocol."""

    def get_cost_config(
        self, market: str, asset_class: str
    ) -> dict[str, Any] | None:
        """
        Get transaction cost configuration for market and asset class.

        Returns:
            Dict with commission_rate, slippage_rate, etc., or None
        """
        ...

    def get_default_cost_config(self, market: str, asset_class: str) -> dict[str, Any]:
        """
        Get default cost configuration.

        Returns:
            Dict with default values
        """
        ...


# =============================================================================
# Market Data Protocol - 行情数据服务协议
# =============================================================================

class MarketDataPort(Protocol):
    """
    Market data service protocol for fetching current prices.

    Defines the interface for fetching real-time or latest market prices.
    Infrastructure layer should implement this protocol using actual data sources.
    """

    def get_current_price(self, asset_code: str) -> Decimal | None:
        """
        Get current price for an asset.

        Args:
            asset_code: Asset code (e.g., 'ASSET_CODE')

        Returns:
            Decimal: Current price, or None if unavailable
        """
        ...

    def get_prices_batch(self, asset_codes: list[str]) -> dict[str, Decimal | None]:
        """
        Get current prices for multiple assets.

        Args:
            asset_codes: List of asset codes

        Returns:
            Dict mapping asset_code to price (None if unavailable)
        """
        ...

    def is_available(self) -> bool:
        """
        Check if the market data service is available.

        Returns:
            True if service is available, False otherwise
        """
        ...


# =============================================================================
# Notification Protocol - 通知服务协议
# =============================================================================

@dataclass
class StopLossNotificationData:
    """Data for stop loss notification."""
    user_id: int
    user_email: str
    position_id: int
    asset_code: str
    trigger_type: str
    trigger_price: Decimal
    trigger_time: Any
    trigger_reason: str
    pnl: Decimal
    pnl_pct: float
    shares_closed: float | None = None


class StopLossNotificationPort(Protocol):
    """
    Stop loss notification service protocol.

    Defines the interface for sending notifications when stop loss is triggered.
    Infrastructure layer should implement this with actual notification mechanisms
    (email, in-app message, etc.).
    """

    def notify_stop_loss_triggered(self, data: StopLossNotificationData) -> bool:
        """
        Send notification when stop loss is triggered.

        Args:
            data: Stop loss notification data

        Returns:
            True if notification was sent successfully, False otherwise
        """
        ...

    def notify_take_profit_triggered(self, data: StopLossNotificationData) -> bool:
        """
        Send notification when take profit is triggered.

        Args:
            data: Take profit notification data

        Returns:
            True if notification was sent successfully, False otherwise
        """
        ...
