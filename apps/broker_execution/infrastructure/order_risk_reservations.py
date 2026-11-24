"""Account-wide live order exposure read under the account binding's checkpoint lock."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Trim, Upper

from apps.broker_execution.application.plan_order_binding import (
    BrokerPlanOrderBindingCorruption,
    BrokerPlanOrderBindingUnavailable,
)
from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.domain.entities import TERMINAL_ORDER_STATUSES, LiveOrderStatus
from apps.broker_execution.domain.plan_order_binding import BrokerPlanOrderBinding
from apps.broker_execution.infrastructure.models import LiveOrderModel
from apps.broker_execution.infrastructure.plan_order_binding_models import (
    BrokerPlanOrderBindingModel,
)
from apps.broker_execution.infrastructure.plan_order_binding_repository import (
    DjangoBrokerPlanOrderBindingRepository,
)


@dataclass(frozen=True, slots=True)
class OrderReservations:
    """Uncredited BUY notional, new held symbols and same-symbol SELL units."""

    buy_amount: Decimal
    symbol_buy_amount: Decimal
    sell_quantity: Decimal
    buy_symbols: frozenset[str]
    buy_estimated_fees: Decimal


def signed_plan_buy_fee(
    *,
    plan: BrokerPlanOrderBinding,
    client_order_id: UUID,
    account_id: int,
    asset_code: str,
    quantity: Decimal,
    limit_price: Decimal,
) -> Decimal:
    """Read the whole approved estimate for this BUY without inventing a fee rate."""
    row = plan.plan_order_payload
    if (
        plan.order_artifact_id != str(client_order_id)
        or plan.broker_account_id != account_id
        or row["side"] != "buy"
        or row["asset_code"] != asset_code
        or row["quantity"] != quantity
        or row["status"] == "blocked"
        or limit_price > Decimal(str(row["reference_price"]))
    ):
        raise BrokerExecutionConflictError("signed_account_risk_plan_fee_scope_mismatch")
    return Decimal(str(row["estimated_fee"]))


class _ReservedOrderPlanReader(DjangoBrokerPlanOrderBindingRepository):
    """Add an exact, bounded historical read using the owner's standard seal restoration."""

    def restore_pinned_bindings(self, hashes: set[str]) -> dict[str, BrokerPlanOrderBinding]:
        """Read immutable creation-time plans for the orders reserving cash."""
        if not transaction.get_connection(self._using).in_atomic_block:
            raise BrokerPlanOrderBindingUnavailable("order reserve reads require a transaction")
        rows = (
            BrokerPlanOrderBindingModel._default_manager.using(self._using)
            .select_for_update(nowait=True)
            .in_bulk(hashes, field_name="content_hash")
        )
        return {seal: self._restore(row) for seal, row in rows.items()}


def _pending_buy_fees(*, orders: list[LiveOrderModel], using: str) -> Decimal:
    pins: dict[str, LiveOrderModel] = {}
    for order in orders:
        pin = order.authority_pin
        seal = pin.get("plan_binding_hash") if isinstance(pin, dict) else None
        if not isinstance(seal, str) or len(seal) != 64 or seal in pins:
            raise BrokerExecutionConflictError("signed_account_risk_plan_fee_unavailable")
        pins[seal] = order
    try:
        plans = _ReservedOrderPlanReader(using=using).restore_pinned_bindings(set(pins))
    except (BrokerPlanOrderBindingCorruption, BrokerPlanOrderBindingUnavailable) as error:
        raise BrokerExecutionConflictError("signed_account_risk_plan_fee_unavailable") from error
    amount = Decimal(0)
    for seal, order in pins.items():
        plan = plans.get(seal)
        if plan is None or order.limit_price is None:
            raise BrokerExecutionConflictError("signed_account_risk_plan_fee_unavailable")
        expected = {
            "order_id": plan.order_artifact_id,
            "order_version": str(plan.order_version),
            "account_id": str(plan.broker_account_id),
            "plan_id": plan.portfolio_plan_id,
            "plan_version": str(plan.portfolio_plan_version),
            "plan_order_hash": plan.plan_order_content_hash,
            "order_artifact_hash": plan.order_artifact_content_hash,
            "plan_approval_hash": plan.portfolio_receipt_content_hash,
        }
        if any(order.authority_pin.get(key) != value for key, value in expected.items()):
            raise BrokerExecutionConflictError("signed_account_risk_plan_fee_unavailable")
        amount += signed_plan_buy_fee(
            plan=plan,
            client_order_id=order.client_order_id,
            account_id=order.account_id,
            asset_code=order.asset_code,
            quantity=order.quantity,
            limit_price=order.limit_price,
        )
    return amount


def read_order_reservations(
    *,
    user_id: int,
    account_id: int,
    client_order_id: UUID,
    asset_code: str,
    sampling_challenge_at: datetime | None,
    using: str,
) -> OrderReservations:
    """Exclude this order. Keep unconfirmed fills reserved until a later full QMT sample."""
    terminal = tuple(status.value for status in TERMINAL_ORDER_STATUSES)
    peers = (
        LiveOrderModel._default_manager.using(using)
        .filter(user_id=user_id, account_id=account_id)
        .exclude(client_order_id=client_order_id)
    )
    if sampling_challenge_at is not None:
        # All asset/position queries began strictly after these completed local receipts.
        peers = peers.exclude(status__in=terminal, updated_at__lt=sampling_challenge_at)
    peers = peers.exclude(
        status__in=(
            LiveOrderStatus.RISK_REJECTED.value,
            LiveOrderStatus.REJECTED.value,
            LiveOrderStatus.EXPIRED.value,
            LiveOrderStatus.FAILED.value,
            LiveOrderStatus.CANCELED.value,
        ),
        filled_quantity=0,
        submitted_at__isnull=True,
        broker_order_id="",
    )
    # A change in the other direction cannot affect a SELL quantity, but all BUYs
    # across symbols affect the shared cash balance and portfolio exposure.
    peers = peers.annotate(reservation_symbol=Upper(Trim("asset_code"))).filter(
        Q(side="BUY") | Q(side="SELL", reservation_symbol=asset_code) | ~Q(side__in=("BUY", "SELL"))
    )
    if sampling_challenge_at is None and peers.filter(status__in=terminal).exists():
        raise BrokerExecutionConflictError("signed_account_risk_sampling_challenge_required")
    buy = Decimal(0)
    symbol_buy = Decimal(0)
    sell = Decimal(0)
    symbols: set[str] = set()
    buys: list[LiveOrderModel] = []
    rows = (
        peers.select_for_update(nowait=True)
        .order_by("pk")
        .only(
            "authority_pin",
            "client_order_id",
            "account_id",
            "status",
            "quantity",
            "filled_quantity",
            "limit_price",
            "asset_code",
            "side",
            "updated_at",
        )
    )
    for row in rows.iterator(chunk_size=256):
        try:
            status = LiveOrderStatus(row.status)
        except ValueError as exc:
            raise BrokerExecutionConflictError("signed_account_risk_reservation_invalid") from exc
        if (
            row.side not in ("BUY", "SELL")
            or not row.asset_code
            or row.quantity <= 0
            or not Decimal(0) <= row.filled_quantity <= row.quantity
        ):
            raise BrokerExecutionConflictError("signed_account_risk_reservation_invalid")
        accounted = sampling_challenge_at is not None and row.updated_at < sampling_challenge_at
        # In-flight unfilled quantity stays reserved even if the broker may also
        # have frozen cash. Do not credit pending sales as additional cash.
        units = (
            row.quantity - row.filled_quantity
            if accounted and status != LiveOrderStatus.RECONCILIATION_REQUIRED
            else row.quantity
        )
        if not units:
            continue
        if row.side == "SELL":
            sell += units
            continue
        if row.limit_price is None or row.limit_price <= 0:
            raise BrokerExecutionConflictError("signed_account_risk_reservation_invalid")
        buys.append(row)
        amount = units * row.limit_price
        buy += amount
        symbol = row.asset_code.strip().upper()
        if not symbol:
            raise BrokerExecutionConflictError("signed_account_risk_reservation_invalid")
        symbols.add(symbol)
        if symbol == asset_code:
            symbol_buy += amount
    return OrderReservations(
        buy, symbol_buy, sell, frozenset(symbols), _pending_buy_fees(orders=buys, using=using)
    )
