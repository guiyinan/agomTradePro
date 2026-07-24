"""Pure domain values for governed broker execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class LiveOrderSide(str, Enum):
    """Supported order directions."""

    BUY = "BUY"
    SELL = "SELL"


class LiveOrderType(str, Enum):
    """Supported broker order types for the first delivery."""

    LIMIT = "LIMIT"


class LiveOrderStatus(str, Enum):
    """Canonical broker-order lifecycle states."""

    DRAFT = "DRAFT"
    RISK_REJECTED = "RISK_REJECTED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    REJECTED = "REJECTED"
    READY = "READY"
    EXPIRED = "EXPIRED"
    LEASED = "LEASED"
    SUBMITTING = "SUBMITTING"
    BROKER_REJECTED = "BROKER_REJECTED"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELED = "CANCELED"


TERMINAL_ORDER_STATUSES = frozenset(
    {
        LiveOrderStatus.RISK_REJECTED,
        LiveOrderStatus.REJECTED,
        LiveOrderStatus.EXPIRED,
        LiveOrderStatus.BROKER_REJECTED,
        LiveOrderStatus.FAILED,
        LiveOrderStatus.FILLED,
        LiveOrderStatus.CANCELED,
    }
)


@dataclass(frozen=True)
class OrderApprovalSnapshot:
    """Immutable fields bound to one human approval."""

    account_id: int
    agent_id: str
    asset_code: str
    market: str
    side: LiveOrderSide
    order_type: LiveOrderType
    quantity: Decimal
    limit_price: Decimal | None
    estimated_amount: Decimal
    expires_at: str
    risk_policy_version: str
    risk_snapshot_json: str
    approval_mode: str
    source_recommendation_ids: tuple[str, ...]
    source_signal_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActorContext:
    """Minimal authenticated actor shape used by application services."""

    user_id: int
    role: str
    is_admin: bool = False
