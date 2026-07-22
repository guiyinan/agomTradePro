"""Repository protocols and read models for the share domain."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
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


class ShareOwnerView(Protocol):
    """Owner fields exposed by a share-link read model."""

    username: str
    email: str

    def get_full_name(self) -> str:
        """Return the owner's display name."""


class ShareLinkView(Protocol):
    """Share-link fields consumed by interface serializers and views."""

    id: int
    owner_id: int
    owner: ShareOwnerView
    account_id: int
    account_name: str
    short_code: str
    title: str
    subtitle: str | None
    theme: str
    status: str
    password_hash: str | None
    expires_at: datetime | None
    max_access_count: int | None
    access_count: int
    last_snapshot_at: datetime | None
    allow_indexing: bool
    show_amounts: bool
    show_positions: bool
    show_transactions: bool
    show_decision_summary: bool
    show_decision_evidence: bool
    show_invalidation_logic: bool
    created_at: datetime

    def is_accessible(self) -> bool:
        """Return whether the public link may be accessed."""

    def requires_password(self) -> bool:
        """Return whether the public link requires a password."""


class ShareSnapshotView(Protocol):
    """Marker protocol for snapshot ORM rows passed to serializers."""

    id: int


class ShareDisclaimerConfigView(Protocol):
    """Disclaimer fields consumed by share management and public pages."""

    is_enabled: bool
    modal_enabled: bool
    modal_title: str
    modal_confirm_text: str
    lines: list[str]


class ShareDecisionFeatureSnapshot(Protocol):
    """Decision feature fields embedded in a public share snapshot."""

    regime: str
    regime_confidence: float
    policy_level: str
    beta_gate_passed: bool
    sentiment_score: float
    flow_score: float
    technical_score: float
    fundamental_score: float
    alpha_model_score: float


class ShareDecisionRecommendation(ShareDecisionFeatureSnapshot, Protocol):
    """Recommendation fields embedded in a public share snapshot."""

    side: str
    confidence: float
    reason_codes: Sequence[str]
    human_rationale: str
    entry_price_low: Decimal
    entry_price_high: Decimal
    target_price_low: Decimal
    target_price_high: Decimal
    stop_loss_price: Decimal
    position_pct: float
    feature_snapshot: ShareDecisionFeatureSnapshot | None


class ShareDecisionResponse(Protocol):
    """Approval response fields embedded in a public share snapshot."""

    approved: bool
    approval_reason: str
    rejection_reason: str
    cooldown_status: str
    quota_status: object | None
    alternative_suggestions: object | None
    responded_at: datetime


class ShareDecisionRequest(Protocol):
    """Decision request shape returned through the cross-app query boundary."""

    asset_code: str
    direction: str
    reason: str
    expected_confidence: float
    requested_at: datetime
    executed_at: datetime | None
    execution_target: str
    execution_status: str
    execution_ref: dict[str, object] | None
    unified_recommendation: ShareDecisionRecommendation | None
    feature_snapshot: ShareDecisionFeatureSnapshot | None
    response: ShareDecisionResponse


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

    def get_share_link_queryset_for_owner(self, owner_id: int) -> Iterable[ShareLinkView]:
        """Return owner-scoped share links ordered newest first."""

    def get_share_link_for_owner(
        self, *, owner_id: int, share_link_id: int
    ) -> ShareLinkView | None:
        """Return one owner-scoped share link when available."""

    def get_share_link_by_id(self, share_link_id: int) -> ShareLinkView | None:
        """Return one share link by id when available."""

    def get_share_link_by_code(self, short_code: str) -> ShareLinkView | None:
        """Return one share link by short code when available."""

    def list_share_snapshots(self, *, share_link_id: int) -> Iterable[ShareSnapshotView]:
        """Return snapshots for one share link."""

    def increment_share_link_access_count(self, *, share_link_id: int) -> None:
        """Increment one share link access counter."""

    def list_owner_accounts(self, owner_id: int) -> list[ShareOwnedAccountSnapshot]:
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

    def list_decision_requests_for_account_assets(
        self, *, account_id: int, asset_codes: set[str]
    ) -> list[ShareDecisionRequest]:
        """Return decision requests relevant to one account and asset set."""

    def get_share_disclaimer_config(self) -> ShareDisclaimerConfigView:
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
    ) -> ShareDisclaimerConfigView:
        """Persist the singleton share disclaimer config."""

    def get_owner_account_name_map(self, owner_id: int) -> dict[int, str]:
        """Return account id to account name mapping for one owner."""
