"""
Account Domain Interfaces

Repository protocols for the account module.
These protocols define the contracts that infrastructure layer must implement.
Application layer should depend on these protocols, not concrete implementations.
"""

from typing import Protocol, List, Optional, Dict, Any
from decimal import Decimal
from datetime import date

from apps.account.domain.entities import (
    AccountProfile,
    Position,
    PortfolioSnapshot,
    Transaction,
    StopLossConfig,
    StopLossTrigger,
)


class AccountRepositoryProtocol(Protocol):
    """Account repository protocol for user account operations."""

    def get_by_user_id(self, user_id: int) -> Optional[AccountProfile]:
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
    ) -> Optional[Dict[str, Any]]:
        """
        Get account profile with volatility configuration.

        Returns:
            Dict with keys: user_id, target_volatility, volatility_tolerance,
            max_volatility_reduction, or None if not found
        """
        ...


class PortfolioRepositoryProtocol(Protocol):
    """Portfolio repository protocol for portfolio operations."""

    def get_user_portfolios(self, user_id: int) -> List[Dict]:
        """Get all portfolios for a user."""
        ...

    def get_portfolio_snapshot(self, portfolio_id: int) -> Optional[PortfolioSnapshot]:
        """Get portfolio snapshot with positions."""
        ...

    def get_active_portfolios(self, user_id: Optional[int] = None) -> List[Dict]:
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
        status: Optional[str] = None,
        asset_class: Optional[str] = None,
    ) -> List[Position]:
        """Get user positions with optional filters."""
        ...

    def get_position_by_id(self, position_id: int) -> Optional[Position]:
        """Get position by ID."""
        ...

    def create_position(
        self,
        portfolio_id: int,
        asset_code: str,
        shares: float,
        price: Decimal,
        source: str = "manual",
        source_id: Optional[int] = None,
    ) -> Position:
        """Create a new position."""
        ...

    def close_position(
        self,
        position_id: int,
        shares: Optional[float] = None,
        price: Optional[Decimal] = None,
        reason: Optional[str] = None,
    ) -> Optional[Position]:
        """Close position (full or partial)."""
        ...

    def update_position_price(
        self, position_id: int, new_price: Decimal
    ) -> Optional[Position]:
        """Update position current price and recalculate P&L."""
        ...

    def get_active_positions_by_portfolio(self, portfolio_id: int) -> List[Position]:
        """Get all active positions for a portfolio."""
        ...

    def get_position_with_user_email(
        self, position_id: int
    ) -> Optional[Dict[str, Any]]:
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
    ) -> List[Transaction]:
        """Get portfolio transactions."""
        ...

    def get_transaction_by_id(self, transaction_id: int) -> Optional[Dict[str, Any]]:
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
        slippage: Optional[Decimal] = None,
        stamp_duty: Optional[Decimal] = None,
        transfer_fee: Optional[Decimal] = None,
        estimated_cost: Optional[Decimal] = None,
    ) -> bool:
        """Update transaction cost fields."""
        ...

    def get_user_transactions_for_analysis(
        self,
        user_id: int,
        portfolio_id: Optional[int] = None,
        days: int = 90,
    ) -> List[Dict[str, Any]]:
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
    ) -> Dict:
        """Get or create asset metadata."""
        ...

    def get_asset_by_code(self, asset_code: str) -> Optional[Dict[str, Any]]:
        """
        Get asset metadata by code.

        Returns:
            Dict with asset_class, region, etc., or None
        """
        ...

    def search_assets(
        self,
        query: str,
        asset_class: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[Dict]:
        """Search assets."""
        ...


class StopLossRepositoryProtocol(Protocol):
    """Stop loss repository protocol for stop loss configuration operations."""

    def get_active_stop_loss_configs(
        self, user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
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
    ) -> Optional[Dict[str, Any]]:
        """Get stop loss config for a position."""
        ...

    def create_stop_loss_config(
        self,
        position_id: int,
        stop_loss_type: str,
        stop_loss_pct: float,
        trailing_stop_pct: Optional[float] = None,
        max_holding_days: Optional[int] = None,
        highest_price: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """Create stop loss configuration."""
        ...

    def update_stop_loss_config(
        self,
        config_id: int,
        status: Optional[str] = None,
        highest_price: Optional[Decimal] = None,
        highest_price_updated_at: Optional[Any] = None,
        triggered_at: Optional[Any] = None,
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
    ) -> Dict[str, Any]:
        """Create stop loss trigger record."""
        ...


class TakeProfitRepositoryProtocol(Protocol):
    """Take profit repository protocol for take profit configuration operations."""

    def get_active_take_profit_configs(
        self, user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
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
    ) -> Optional[Dict[str, Any]]:
        """Get take profit config for a position."""
        ...

    def create_take_profit_config(
        self,
        position_id: int,
        take_profit_pct: float,
        partial_profit_levels: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Create take profit configuration."""
        ...

    def update_take_profit_config(
        self,
        config_id: int,
        is_active: Optional[bool] = None,
    ) -> bool:
        """Update take profit configuration."""
        ...


class PortfolioSnapshotRepositoryProtocol(Protocol):
    """Portfolio snapshot repository protocol for historical data."""

    def get_snapshots_for_volatility(
        self,
        portfolio_id: int,
        days: int = 90,
    ) -> List[Dict[str, Any]]:
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
    ) -> Optional[Dict[str, Any]]:
        """
        Get transaction cost configuration for market and asset class.

        Returns:
            Dict with commission_rate, slippage_rate, etc., or None
        """
        ...

    def get_default_cost_config(self, market: str, asset_class: str) -> Dict[str, Any]:
        """
        Get default cost configuration.

        Returns:
            Dict with default values
        """
        ...
