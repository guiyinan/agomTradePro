"""Repository protocols and read models for the share domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Protocol

from .entities import ShareLinkEntity


@dataclass(frozen=True)
class ShareOwnedAccountSnapshot:
    """Account snapshot fields required to build a share snapshot payload."""

    id: int
    account_name: str
    account_type: str | None
    start_date: date | None
    total_value: Decimal | float | int | None
    current_market_value: Decimal | float | int | None
    current_cash: Decimal | float | int | None
    total_return: Decimal | float | int | None
    annual_return: Decimal | float | int | None
    max_drawdown: Decimal | float | int | None
    sharpe_ratio: Decimal | float | int | None
    win_rate: Decimal | float | int | None
    total_trades: int | None


@dataclass(frozen=True)
class ShareOwnedPositionSnapshot:
    """Position fields required for share snapshot rendering."""

    asset_code: str | None
    asset_name: str | None
    asset_type: str | None
    quantity: Decimal | float | int | None
    avg_cost: Decimal | float | int | None
    current_price: Decimal | float | int | None
    market_value: Decimal | float | int | None
    unrealized_pnl: Decimal | float | int | None
    unrealized_pnl_pct: Decimal | float | int | None
    entry_reason: str | None
    invalidation_description: str | None


@dataclass(frozen=True)
class ShareOwnedTradeSnapshot:
    """Trade fields required for share snapshot rendering."""

    asset_code: str | None
    asset_name: str | None
    action: str | None
    quantity: Decimal | float | int | None
    price: Decimal | float | int | None
    amount: Decimal | float | int | None
    reason: str | None
    execution_time: datetime | time | None
    status: str | None


class ShareApplicationRepositoryProtocol(Protocol):
    """Repository operations required by share application use cases."""

    def user_exists(self, owner_id: int) -> bool:
        """Return whether the share owner exists."""

    def account_belongs_to_owner(self, *, owner_id: int, account_id: int) -> bool:
        """Return whether the target account belongs to the owner."""

    def share_link_short_code_exists(self, short_code: str) -> bool:
        """Return whether one public short code already exists."""

    def create_share_link(self, **payload: Any) -> ShareLinkEntity:
        """Persist a new share link and return the resulting entity."""

    def get_share_link(self, share_link_id: int) -> ShareLinkEntity | None:
        """Return one share link entity by id when available."""

    def get_share_link_by_code(self, short_code: str) -> ShareLinkEntity | None:
        """Return one share link entity by public short code when available."""

    def list_share_links(
        self,
        *,
        owner_id: int | None = None,
        account_id: int | None = None,
        status: str | None = None,
        share_level: str | None = None,
    ) -> list[ShareLinkEntity]:
        """Return share links filtered by the provided criteria."""

    def update_share_link_fields(
        self,
        *,
        share_link_id: int,
        updates: dict[str, Any],
    ) -> ShareLinkEntity | None:
        """Persist field updates and return the refreshed share link entity."""

    def revoke_share_link(self, *, share_link_id: int, owner_id: int) -> bool:
        """Mark one owner-scoped share link as revoked."""

    def delete_share_link(self, *, share_link_id: int, owner_id: int) -> bool:
        """Delete one owner-scoped share link."""

    def create_snapshot(
        self,
        *,
        share_link_id: int,
        summary_payload: dict[str, Any],
        performance_payload: dict[str, Any],
        positions_payload: dict[str, Any],
        transactions_payload: dict[str, Any],
        decision_payload: dict[str, Any],
        source_range_start: date | None = None,
        source_range_end: date | None = None,
    ) -> int | None:
        """Persist a snapshot and return its id when the share link exists."""

    def get_latest_snapshot(self, share_link_id: int) -> dict[str, Any] | None:
        """Return the latest share snapshot payload when available."""

    def log_access(
        self,
        *,
        share_link_id: int,
        ip_hash: str,
        user_agent: str | None = None,
        referer: str | None = None,
        result_status: str = "success",
        is_verified: bool = False,
    ) -> int:
        """Persist one access log entry and return its id."""

    def get_access_logs(
        self,
        *,
        share_link_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return access log rows ordered newest first."""

    def get_access_stats(self, *, share_link_id: int) -> dict[str, int]:
        """Return aggregate access statistics for one share link."""


class ShareInterfaceRepositoryProtocol(Protocol):
    """Repository operations required by share interface services."""

    def get_share_link_queryset_for_owner(self, owner_id: int):
        """Return owner-scoped share links ordered newest first."""

    def get_share_link_for_owner(self, *, owner_id: int, share_link_id: int):
        """Return one owner-scoped share link when available."""

    def get_share_link_by_id(self, share_link_id: int):
        """Return one share link by id when available."""

    def get_share_link_by_code(self, short_code: str):
        """Return one share link by short code when available."""

    def list_share_snapshots(self, *, share_link_id: int):
        """Return snapshots for one share link."""

    def increment_share_link_access_count(self, *, share_link_id: int) -> None:
        """Increment one share link access counter."""

    def list_owner_accounts(self, owner_id: int):
        """Return owner accounts for share management screens."""

    def get_owned_account_for_snapshot(
        self,
        *,
        owner_id: int,
        account_id: int,
    ) -> ShareOwnedAccountSnapshot | None:
        """Return account fields required to build a share snapshot."""

    def list_owned_account_positions_for_snapshot(
        self,
        *,
        owner_id: int,
        account_id: int,
    ) -> list[ShareOwnedPositionSnapshot]:
        """Return ordered positions for share snapshot generation."""

    def list_owned_account_trades_for_snapshot(
        self,
        *,
        owner_id: int,
        account_id: int,
        limit: int = 20,
    ) -> list[ShareOwnedTradeSnapshot]:
        """Return ordered trades for share snapshot generation."""

    def account_belongs_to_owner(self, *, owner_id: int, account_id: int) -> bool:
        """Return whether an account belongs to the given owner."""

    def list_decision_requests_for_account_assets(self, *, account_id: int, asset_codes: set[str]):
        """Return decision requests relevant to one account and asset set."""

    def get_share_disclaimer_config(self):
        """Return the singleton share disclaimer config."""

    def has_share_disclaimer_config(self) -> bool:
        """Return whether the disclaimer config exists."""

    def update_share_disclaimer_config(
        self,
        *,
        is_enabled: bool,
        modal_enabled: bool,
        modal_title: str,
        modal_confirm_text: str,
        lines: list[str],
    ):
        """Persist the singleton share disclaimer config."""

    def get_owner_account_name_map(self, owner_id: int) -> dict[int, str]:
        """Return account id to account name mapping for one owner."""
