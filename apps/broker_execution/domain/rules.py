"""Pure broker-execution rules."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime, time

from .entities import LiveOrderStatus, OrderApprovalSnapshot


class InvalidOrderTransitionError(ValueError):
    """Raised when an order lifecycle transition is not permitted."""


def is_trading_session_open(now: datetime, windows: Iterable[str]) -> bool:
    """Return whether an aware local time is a weekday inside a configured window."""

    if now.weekday() >= 5:
        return False
    current = now.timetz().replace(tzinfo=None)
    for window in windows:
        try:
            start_text, end_text = str(window).split("-", 1)
            start = time.fromisoformat(start_text)
            end = time.fromisoformat(end_text)
        except (TypeError, ValueError):
            continue
        if start <= current <= end:
            return True
    return False


_TRANSITIONS: dict[LiveOrderStatus, frozenset[LiveOrderStatus]] = {
    LiveOrderStatus.DRAFT: frozenset(
        {LiveOrderStatus.RISK_REJECTED, LiveOrderStatus.WAITING_APPROVAL}
    ),
    LiveOrderStatus.WAITING_APPROVAL: frozenset(
        {
            LiveOrderStatus.REJECTED,
            LiveOrderStatus.CANCELED,
            LiveOrderStatus.READY,
            LiveOrderStatus.EXPIRED,
            LiveOrderStatus.RECONCILIATION_REQUIRED,
        }
    ),
    LiveOrderStatus.READY: frozenset(
        {
            LiveOrderStatus.CANCELED,
            LiveOrderStatus.LEASED,
            LiveOrderStatus.EXPIRED,
            LiveOrderStatus.RECONCILIATION_REQUIRED,
        }
    ),
    LiveOrderStatus.LEASED: frozenset(
        {
            LiveOrderStatus.CANCELED,
            LiveOrderStatus.READY,
            LiveOrderStatus.SUBMITTING,
            LiveOrderStatus.EXPIRED,
            LiveOrderStatus.RECONCILIATION_REQUIRED,
        }
    ),
    LiveOrderStatus.SUBMITTING: frozenset(
        {
            LiveOrderStatus.BROKER_REJECTED,
            LiveOrderStatus.FAILED,
            LiveOrderStatus.RECONCILIATION_REQUIRED,
            LiveOrderStatus.SUBMITTED,
        }
    ),
    LiveOrderStatus.SUBMITTED: frozenset(
        {
            LiveOrderStatus.BROKER_REJECTED,
            LiveOrderStatus.PARTIALLY_FILLED,
            LiveOrderStatus.FILLED,
            LiveOrderStatus.CANCEL_PENDING,
            LiveOrderStatus.CANCELED,
            LiveOrderStatus.RECONCILIATION_REQUIRED,
        }
    ),
    LiveOrderStatus.PARTIALLY_FILLED: frozenset(
        {
            LiveOrderStatus.FILLED,
            LiveOrderStatus.CANCEL_PENDING,
            LiveOrderStatus.CANCELED,
            LiveOrderStatus.RECONCILIATION_REQUIRED,
        }
    ),
    LiveOrderStatus.CANCEL_PENDING: frozenset(
        {
            LiveOrderStatus.CANCELED,
            LiveOrderStatus.PARTIALLY_FILLED,
            LiveOrderStatus.FILLED,
            LiveOrderStatus.RECONCILIATION_REQUIRED,
        }
    ),
    LiveOrderStatus.RECONCILIATION_REQUIRED: frozenset(
        {
            LiveOrderStatus.SUBMITTED,
            LiveOrderStatus.PARTIALLY_FILLED,
            LiveOrderStatus.FILLED,
            LiveOrderStatus.CANCELED,
            LiveOrderStatus.BROKER_REJECTED,
        }
    ),
}


def validate_order_transition(current: str, target: str) -> None:
    """Validate one canonical order-state transition."""

    current_status = LiveOrderStatus(current)
    target_status = LiveOrderStatus(target)
    if target_status not in _TRANSITIONS.get(current_status, frozenset()):
        raise InvalidOrderTransitionError(
            f"Order cannot transition from {current_status.value} to {target_status.value}"
        )


def target_status_for_order_action(current: str, action: str) -> LiveOrderStatus:
    """Return and validate the canonical target for a human order action."""

    normalized_action = str(action).strip().lower()
    current_status = LiveOrderStatus(current)
    if normalized_action == "approve":
        target = LiveOrderStatus.READY
    elif normalized_action == "reject":
        target = LiveOrderStatus.REJECTED
    elif normalized_action == "cancel":
        target = (
            LiveOrderStatus.CANCELED
            if current_status
            in {
                LiveOrderStatus.WAITING_APPROVAL,
                LiveOrderStatus.READY,
                LiveOrderStatus.LEASED,
            }
            else LiveOrderStatus.CANCEL_PENDING
        )
    else:
        raise InvalidOrderTransitionError(f"Unsupported order action {normalized_action!r}")
    validate_order_transition(current_status.value, target.value)
    return target


def build_approval_digest(snapshot: OrderApprovalSnapshot) -> str:
    """Return a stable SHA-256 digest for approval-bound order fields."""

    payload = asdict(snapshot)
    payload["side"] = snapshot.side.value
    payload["order_type"] = snapshot.order_type.value
    payload["quantity"] = str(snapshot.quantity)
    payload["limit_price"] = str(snapshot.limit_price) if snapshot.limit_price is not None else None
    payload["estimated_amount"] = str(snapshot.estimated_amount)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
