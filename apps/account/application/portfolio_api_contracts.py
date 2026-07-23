"""Typed ports for the Account portfolio API application boundary."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol


class AccountUserRecord(Protocol):
    """Minimal user projection consumed by portfolio API handlers."""

    id: int
    username: str


class PortfolioRecord(Protocol):
    """Minimal legacy portfolio projection used by the application service."""

    id: int
    user_id: int
    user: AccountUserRecord
    name: str
    is_active: bool


class LegacyPositionRecord(Protocol):
    """Legacy Account position projection mirrored from the unified ledger."""

    id: int
    portfolio: PortfolioRecord
    asset_code: str
    shares: float
    avg_cost: Decimal
    current_price: Decimal | None
    asset_class: str
    region: str
    cross_border: str
    category: object | None
    currency: object | None
    source: str
    source_id: int | None
    is_closed: bool


class UnifiedPositionRecord(Protocol):
    """Unified ledger position fields consumed by Account orchestration."""

    id: int
    account_id: int
    asset_code: str
    asset_name: str
    asset_type: str
    signal_id: int | None


class ObserverGrantRecord(Protocol):
    """Observer grant behavior required by access validation."""

    def is_valid(self) -> bool:
        """Return whether the grant is currently usable."""

    def get_status_display(self) -> str:
        """Return the localized grant status."""


class PositionMappingRecord(Protocol):
    """Legacy-to-unified position mapping projection."""

    target_id: int


class PortfolioQuerySet(Protocol):
    """Small queryset surface retained at the HTTP pagination boundary."""

    def select_related(self, *fields: str) -> PortfolioQuerySet:
        """Return a queryset with the requested relations joined."""

    def filter(self, **lookups: object) -> PortfolioQuerySet:
        """Return a queryset narrowed by ORM lookups."""

    def __iter__(self) -> Iterator[PortfolioRecord]:
        """Iterate accessible portfolios."""


class PortfolioApiRepository(Protocol):
    """Persistence port for portfolio access and ledger projection orchestration."""

    def get_portfolio_with_owner(self, portfolio_id: int) -> PortfolioRecord | None:
        """Return one portfolio with its owner loaded."""

    def get_active_observer_grant(
        self, *, owner_user_id: int, observer_user_id: int
    ) -> ObserverGrantRecord | None:
        """Return an active observer grant when present."""

    def get_inactive_observer_grant(
        self, *, owner_user_id: int, observer_user_id: int
    ) -> ObserverGrantRecord | None:
        """Return the most recent inactive observer grant when present."""

    def ensure_real_account(self, portfolio: PortfolioRecord) -> int:
        """Return the unified real-account id for a portfolio."""

    def get_portfolio_for_account(self, account_id: int) -> PortfolioRecord | None:
        """Return the legacy portfolio mapped to a unified account."""

    def list_open_legacy_positions(self, portfolio: PortfolioRecord) -> list[LegacyPositionRecord]:
        """Return open legacy positions for synchronization."""

    def get_legacy_position_by_id(self, position_id: int) -> LegacyPositionRecord | None:
        """Return one legacy position projection."""

    def get_legacy_projection_for_unified_position(
        self, unified_position_id: int
    ) -> LegacyPositionRecord | None:
        """Return the legacy projection mapped to a unified position."""

    def get_position_mapping_for_source(self, source_id: int) -> PositionMappingRecord | None:
        """Return a legacy-to-unified mapping."""

    def create_position_mapping(self, *, source_id: int, target_id: int) -> None:
        """Create a legacy-to-unified position mapping."""

    def delete_position_mapping_for_source(self, source_id: int) -> None:
        """Delete a mapping by legacy source id."""

    def delete_position_mapping_for_target(self, target_id: int) -> None:
        """Delete mappings by unified target id."""

    def get_unified_position(self, position_id: int) -> UnifiedPositionRecord | None:
        """Return one unified position."""

    def get_unified_position_for_account_asset(
        self, *, account_id: int, asset_code: str
    ) -> UnifiedPositionRecord | None:
        """Return one unified position by account and asset."""

    def list_unified_positions(
        self, *, account_ids: list[int], asset_code: str | None = None
    ) -> list[UnifiedPositionRecord]:
        """Return unified positions for the requested accounts."""

    def delete_unified_position(self, position_id: int) -> None:
        """Delete one unified position."""

    def delete_legacy_projection(self, legacy_projection: LegacyPositionRecord) -> None:
        """Delete one legacy projection."""

    def upsert_legacy_projection_from_unified(
        self,
        *,
        unified_position: UnifiedPositionRecord,
        portfolio: PortfolioRecord,
        asset_class: str,
        region: str,
        cross_border: str,
        category: object | None = None,
        currency: object | None = None,
        source: str = "manual",
        source_id: int | None = None,
        close_projection: bool = False,
    ) -> LegacyPositionRecord | None:
        """Create or refresh a legacy position projection."""

    def mark_legacy_projection_closed_for_unified(
        self, *, target_id: int, closed_at: datetime | None = None
    ) -> LegacyPositionRecord | None:
        """Mark a legacy projection closed."""

    def build_position_payload(
        self,
        unified_position: UnifiedPositionRecord,
        portfolio: PortfolioRecord | None = None,
    ) -> dict[str, Any]:
        """Build an API position payload."""

    def build_closed_position_payload(
        self,
        *,
        unified_position: UnifiedPositionRecord,
        portfolio: PortfolioRecord,
        legacy_projection: LegacyPositionRecord | None,
    ) -> dict[str, Any]:
        """Build the payload for a fully closed position."""

    def build_portfolio_statistics(self, portfolio: PortfolioRecord) -> dict[str, Any]:
        """Build portfolio summary statistics."""


class AccountInterfaceRepository(Protocol):
    """Read port for accessible portfolio querysets."""

    def get_accessible_portfolios_queryset(self, user_id: int) -> PortfolioQuerySet:
        """Return portfolios visible to a user."""


class AccountReadRepository(Protocol):
    """Side-effect-free position payload read port."""

    def list_open_legacy_position_payloads(
        self, portfolio: PortfolioRecord
    ) -> list[dict[str, Any]]:
        """Return open legacy positions for one portfolio."""

    def list_position_payloads(
        self,
        *,
        user_id: int,
        portfolio_id: int | None = None,
        asset_code: str | None = None,
        include_closed: bool = False,
    ) -> list[dict[str, Any]]:
        """Return accessible legacy position payloads."""


class LegacyPositionMutationRepository(Protocol):
    """Legacy close operation retained during ledger migration."""

    def close_position(
        self,
        position_id: int,
        shares: float | None = None,
        price: Decimal | None = None,
        reason: str | None = None,
    ) -> object | None:
        """Close all or part of one legacy position."""


class UnifiedPositionService(Protocol):
    """Unified ledger lifecycle port used by Account."""

    def create_position(
        self,
        account_id: int,
        asset_code: str,
        shares: float | Decimal,
        price: float | Decimal,
        *,
        current_price: float | Decimal | None = None,
        asset_name: str = "",
        asset_type: str = "equity",
        source: str = "manual",
        source_id: int | None = None,
        entry_reason: str = "",
        traded_at: datetime | None = None,
    ) -> UnifiedPositionRecord:
        """Open or merge a unified position."""

    def update_position(
        self,
        account_id: int,
        asset_code: str,
        *,
        shares: float | Decimal | None = None,
        avg_cost: float | Decimal | None = None,
        current_price: float | Decimal | None = None,
    ) -> object | None:
        """Update a unified position."""

    def close_position(
        self,
        account_id: int,
        asset_code: str,
        *,
        close_shares: float | Decimal | None = None,
        close_price: float | Decimal | None = None,
        reason: str = "平仓",
        traded_at: datetime | None = None,
    ) -> object | None:
        """Close all or part of a unified position."""


__all__ = [
    "AccountInterfaceRepository",
    "AccountReadRepository",
    "LegacyPositionMutationRepository",
    "LegacyPositionRecord",
    "PortfolioApiRepository",
    "PortfolioQuerySet",
    "PortfolioRecord",
    "UnifiedPositionRecord",
    "UnifiedPositionService",
]
