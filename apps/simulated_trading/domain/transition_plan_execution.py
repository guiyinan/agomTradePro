"""Pure reconciliation rules for approved portfolio-plan order execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256
from typing import Literal, Protocol, runtime_checkable

from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationStatus,
)

PlanExecutionOutcome = Literal[
    "ready", "in_flight", "complete", "successor_required", "blocked", "unknown"
]


@runtime_checkable
class PlanOrderExecutionBinding(Protocol):
    """Structural contract for Portfolio's single canonical execution binding."""

    @property
    def plan_id(self) -> str: ...

    @property
    def family_id(self) -> str: ...

    @property
    def root_plan_id(self) -> str: ...

    @property
    def plan_version(self) -> int: ...

    @property
    def revision_hash(self) -> str: ...

    @property
    def order_ordinal(self) -> int: ...

    @property
    def plan_order_binding_id(self) -> str: ...

    @property
    def order_content_hash(self) -> str: ...

    @property
    def account_id(self) -> int: ...

    @property
    def owner_user_id(self) -> int: ...

    @property
    def action_attempt_key(self) -> str: ...

    @property
    def asset_code(self) -> str: ...

    @property
    def security_id(self) -> str: ...

    @property
    def asset_type(self) -> str: ...

    @property
    def classification_content_hash(self) -> str: ...

    @property
    def side(self) -> Literal["buy", "sell"]: ...

    @property
    def approved_quantity(self) -> int: ...

    @property
    def approved_limit_price(self) -> Decimal | None: ...

    @property
    def quantity_unit(self) -> str: ...

    @property
    def money_unit(self) -> str: ...

    @property
    def plan_expires_at(self) -> datetime: ...

    @property
    def content_hash(self) -> str:
        """Return Portfolio's canonical digest of this exact binding."""

    def to_payload(self) -> dict[str, object]:
        """Return the Portfolio-owned canonical binding payload."""

    def __post_init__(self) -> None:
        """Validate the Portfolio-owned binding fields."""


@runtime_checkable
class PlanRevisionExecutionIdentity(Protocol):
    """Structural identity of one Portfolio revision used for read-side progress."""

    @property
    def plan_id(self) -> str: ...

    @property
    def family_id(self) -> str: ...

    @property
    def root_plan_id(self) -> str: ...

    @property
    def version(self) -> int: ...

    @property
    def revision_hash(self) -> str: ...

    @property
    def account_id(self) -> int: ...

    @property
    def owner_user_id(self) -> int: ...

    @property
    def recorded_at(self) -> datetime: ...

    @property
    def valid_until(self) -> datetime: ...

    def __post_init__(self) -> None:
        """Validate the exact Portfolio revision identity."""


@runtime_checkable
class PlanOrderExecutionReference(Protocol):
    """Immutable order terms from a revision, without inventing an action attempt."""

    @property
    def ordinal(self) -> int: ...

    @property
    def order_content_hash(self) -> str: ...

    @property
    def plan_order_binding_id(self) -> str: ...

    @property
    def asset_code(self) -> str: ...

    @property
    def security_id(self) -> str: ...

    @property
    def asset_type(self) -> str: ...

    @property
    def classification_content_hash(self) -> str: ...

    @property
    def side(self) -> Literal["buy", "sell"]: ...

    @property
    def approved_quantity(self) -> int: ...

    @property
    def approved_limit_price(self) -> Decimal | None: ...

    @property
    def quantity_unit(self) -> str: ...

    @property
    def money_unit(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def reason_codes(self) -> tuple[str, ...]: ...

    def __post_init__(self) -> None:
        """Validate the exact immutable Portfolio order binding."""


def _require_binding(value: object) -> PlanOrderExecutionBinding:
    """Narrow one public Portfolio execution binding without duplicating its DTO."""

    if not isinstance(value, PlanOrderExecutionBinding):
        raise ValueError("an exact Portfolio plan-order execution binding is required")
    value.__post_init__()
    if type(value.to_payload()) is not dict:
        raise ValueError("Portfolio plan-order binding payload is invalid")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    """Return an exact timezone-aware instant without changing its source offset."""

    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{field_name} must be an aware datetime")
    try:
        if value.utcoffset() is None:
            raise ValueError(f"{field_name} has no UTC offset")
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{field_name} has an invalid UTC offset") from error
    return value


def _require_quantity(value: object, field_name: str, *, allow_zero: bool = True) -> Decimal:
    """Require an exact finite nonnegative ledger quantity."""

    if type(value) is not Decimal or not value.is_finite() or value < 0:
        raise ValueError(f"{field_name} must be a finite nonnegative Decimal")
    if not allow_zero and value == 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _sum_quantities(values: tuple[Decimal, ...]) -> Decimal:
    """Sum exact finite quantities without inheriting a caller Decimal context."""

    with localcontext() as context:
        context.prec = 80
        return sum(values, Decimal("0"))


def derive_plan_order_idempotency_key(binding_content_hash: str) -> str:
    """Derive an order key that identifies one exact, action-bound plan line."""

    if (
        type(binding_content_hash) is not str
        or len(binding_content_hash) != 64
        or any(char not in "0123456789abcdef" for char in binding_content_hash)
    ):
        raise ValueError("binding_content_hash must be lowercase SHA-256")
    digest = sha256(f"ash08-plan-order:v1:{binding_content_hash}".encode("ascii")).hexdigest()
    return f"ash08-{digest}"


@dataclass(frozen=True, slots=True)
class VerifiedPlanFill:
    """One fill already verified against its retained receipt and actual trade row."""

    receipt_id: int
    trade_id: int
    quantity: Decimal
    gross_amount: Decimal
    actual_fee: Decimal | None

    def __post_init__(self) -> None:
        """Validate receipt identity and preserve unknown actual fee as unknown."""

        for name in ("receipt_id", "trade_id"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        _require_quantity(self.quantity, "fill quantity", allow_zero=False)
        if (
            type(self.gross_amount) is not Decimal
            or not self.gross_amount.is_finite()
            or self.gross_amount <= 0
        ):
            raise ValueError("fill gross amount must be a positive Decimal")
        if self.actual_fee is not None and (
            type(self.actual_fee) is not Decimal
            or not self.actual_fee.is_finite()
            or self.actual_fee < 0
        ):
            raise ValueError("actual_fee must be a finite nonnegative Decimal or None")


@dataclass(frozen=True, slots=True)
class PlanExecutionAttemptProgress:
    """Read-only facts for one actual, idempotency-keyed order attempt."""

    action_attempt_key: str
    reservation_id: int
    status: Literal["active", "completed", "cancelled"]
    reserved_quantity: Decimal
    filled_quantity: Decimal | None
    gross_filled_value: Decimal | None
    remaining_quantity: Decimal
    remaining_cash_held: Decimal
    cash_consumed: Decimal
    cash_released: Decimal
    actual_fees_paid: Decimal | None
    fees_complete: bool
    fill_receipt_ids: tuple[int, ...]
    trade_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PlanExecutionReservation:
    """One existing reservation and its fully verified, possibly incomplete fill history."""

    reservation_id: int
    binding: PlanOrderExecutionBinding
    revision_recorded_at: datetime
    intent: SimulatedTradeIntent
    reservation: OrderReservation
    fills: tuple[VerifiedPlanFill, ...] | None

    def __post_init__(self) -> None:
        """Bind existing order economics to one canonical plan action binding."""

        if type(self.reservation_id) is not int or self.reservation_id <= 0:
            raise ValueError("reservation_id must be positive")
        binding = _require_binding(self.binding)
        recorded_at = _require_aware(self.revision_recorded_at, "revision_recorded_at")
        if recorded_at >= binding.plan_expires_at:
            raise ValueError("plan revision must be recorded before its expiry")
        if type(self.intent) is not SimulatedTradeIntent:
            raise ValueError("reservation intent must be the exact persisted trade intent")
        self.intent.__post_init__()
        if type(self.reservation) is not OrderReservation:
            raise ValueError("reservation must be an exact existing order reservation")
        self.reservation.__post_init__()
        if self.fills is not None:
            if type(self.fills) is not tuple or any(
                type(item) is not VerifiedPlanFill for item in self.fills
            ):
                raise ValueError("fills must be a tuple of verified fill facts or None")
            for item in self.fills:
                item.__post_init__()
        if (
            self.reservation.identity.account_id != binding.account_id
            or self.reservation.identity.security_id != binding.security_id
            or self.reservation.identity.idempotency_key
            != derive_plan_order_idempotency_key(binding.content_hash)
            or self.reservation.side.value != binding.side
            or self.reservation.quantity > Decimal(binding.approved_quantity)
            or (
                self.intent.account_id,
                self.intent.user_id,
                self.intent.idempotency_key,
                self.intent.asset_code,
                self.intent.asset_type,
                self.intent.security_id,
                self.intent.side.value,
            )
            != (
                binding.account_id,
                binding.owner_user_id,
                derive_plan_order_idempotency_key(binding.content_hash),
                binding.asset_code,
                binding.asset_type,
                binding.security_id,
                binding.side,
            )
            or self.intent.quantity != self.reservation.quantity
            or self.intent.price != self.reservation.limit_price
            or (
                binding.approved_limit_price is not None
                and self.intent.price != binding.approved_limit_price
            )
        ):
            raise ValueError("reservation identity differs from its plan action binding")
        if self.fills is not None and _sum_quantities(
            tuple(item.quantity for item in self.fills)
        ) != (self.reservation.filled_quantity):
            raise ValueError("verified fill quantity differs from reservation cumulative fills")


@dataclass(frozen=True, slots=True)
class PlanOrderExecutionProgress:
    """Reconciled order totals and capabilities; unknown history never becomes zero."""

    revision_identity: PlanRevisionExecutionIdentity
    order: PlanOrderExecutionReference
    outcome: PlanExecutionOutcome
    approved_quantity: int
    filled_quantity: Decimal | None
    in_flight_quantity: Decimal | None
    family_in_flight_quantity: Decimal | None
    released_quantity: Decimal | None
    remaining_quantity: Decimal | None
    unreserved_remaining_quantity: Decimal | None
    reserved_buy_cash: Decimal | None
    released_buy_cash: Decimal | None
    active_sell_quantity: Decimal | None
    actual_fees_paid: Decimal | None
    fees_complete: bool
    active_order_ids: tuple[int, ...]
    family_active_order_ids: tuple[int, ...]
    completed_order_ids: tuple[int, ...]
    cancelled_order_ids: tuple[int, ...]
    replay_order_id: int | None
    attempts: tuple[PlanExecutionAttemptProgress, ...]
    action_attempt_keys: tuple[str, ...]
    predecessor_sells_settled: bool | None
    can_recover: bool
    can_preview: bool
    can_cancel: bool
    requires_successor: bool
    reason_codes: tuple[str, ...]


def reconcile_plan_order_execution(
    *,
    revision_identity: PlanRevisionExecutionIdentity,
    order: PlanOrderExecutionReference,
    reservations: tuple[PlanExecutionReservation, ...],
    related_family_reservations: tuple[PlanExecutionReservation, ...],
    history_complete: bool,
    revision_active: bool,
    as_of: datetime,
    predecessor_sells_settled: bool | None,
    expected_action_attempt_key: str | None = None,
) -> PlanOrderExecutionProgress:
    """Reconcile one exact plan line against durable holds and verified fills.

    The function does not post fills, cancel reservations, release cash, infer
    sale proceeds, or grant execution authority. Reservation and fill facts are
    the only quantities counted; predecessor-sale state is supplied only when
    an exact plan binding explicitly records that funding dependency.
    """

    if not isinstance(revision_identity, PlanRevisionExecutionIdentity):
        raise ValueError("an exact Portfolio revision identity is required")
    if not isinstance(order, PlanOrderExecutionReference):
        raise ValueError("an exact Portfolio order reference is required")
    revision_identity.__post_init__()
    order.__post_init__()
    _require_aware(as_of, "as_of")
    if type(history_complete) is not bool or type(revision_active) is not bool:
        raise ValueError("history and revision qualification flags must be booleans")
    if predecessor_sells_settled is not None and type(predecessor_sells_settled) is not bool:
        raise ValueError("predecessor_sells_settled must be bool or None")
    if expected_action_attempt_key is not None and (
        type(expected_action_attempt_key) is not str or not expected_action_attempt_key.strip()
    ):
        raise ValueError("expected_action_attempt_key must be absent or nonempty")

    identity = revision_identity
    if (
        order.approved_quantity < 0
        or order.ordinal < 0
        or type(order.approved_quantity) is not int
        or identity.account_id <= 0
        or identity.owner_user_id <= 0
    ):
        raise ValueError("plan order scope is invalid")

    reason_codes: list[str] = []
    approved = order.approved_quantity
    approved_decimal = Decimal(approved)
    if as_of >= identity.valid_until:
        reason_codes.append("TRANSITION_PLAN_EXPIRED")
    if identity.recorded_at > as_of:
        reason_codes.append("TRANSITION_PLAN_NOT_YET_KNOWN")
    if order.approved_quantity == 0 or order.status == "blocked":
        reason_codes.append("TRANSITION_PLAN_ORDER_NOT_EXECUTABLE")
    if not revision_active:
        reason_codes.append("TRANSITION_PLAN_REVISION_NOT_ACTIVE")
    if not history_complete:
        reason_codes.append("TRANSITION_PLAN_EXECUTION_HISTORY_INCOMPLETE")

    all_rows = (*reservations, *related_family_reservations)
    reservation_ids: set[int] = set()
    attempt_keys: set[str] = set()
    for item in all_rows:
        if type(item) is not PlanExecutionReservation:
            raise ValueError("reservation history contains an unknown typed row")
        item.__post_init__()
        if item.reservation_id in reservation_ids:
            reason_codes.append("TRANSITION_PLAN_DUPLICATE_RESERVATION_ID")
        reservation_ids.add(item.reservation_id)
        if item.binding.action_attempt_key in attempt_keys:
            reason_codes.append("TRANSITION_PLAN_DUPLICATE_ACTION_ATTEMPT")
        attempt_keys.add(item.binding.action_attempt_key)
        row_binding = item.binding
        if (
            row_binding.account_id != identity.account_id
            or row_binding.owner_user_id != identity.owner_user_id
            or row_binding.family_id != identity.family_id
            or row_binding.root_plan_id != identity.root_plan_id
        ):
            reason_codes.append("TRANSITION_PLAN_EXECUTION_SCOPE_MISMATCH")

    current_rows = tuple(
        item for item in reservations if _same_plan_order(item.binding, identity, order)
    )
    if len(current_rows) > 1:
        reason_codes.append("TRANSITION_PLAN_MULTIPLE_ATTEMPTS_FOR_ORDER")
    matching_attempts = tuple(
        item
        for item in current_rows
        if expected_action_attempt_key is not None
        and item.binding.action_attempt_key == expected_action_attempt_key
    )
    replay_order_id: int | None = None
    if len(matching_attempts) > 1:
        reason_codes.append("TRANSITION_PLAN_DUPLICATE_ACTION_ATTEMPT")
    elif matching_attempts:
        replay_order_id = matching_attempts[0].reservation_id
    for item in current_rows:
        if not _reservation_binding_matches_order(
            item.binding,
            revision_identity=identity,
            order=order,
            revision_recorded_at=item.revision_recorded_at,
        ):
            reason_codes.append("TRANSITION_PLAN_ORDER_BINDING_MISMATCH")

    related_active = tuple(
        item
        for item in related_family_reservations
        if item.binding.asset_code == order.asset_code
        and item.binding.security_id == order.security_id
        and item.reservation.status is OrderReservationStatus.ACTIVE
    )
    if related_active:
        reason_codes.append("TRANSITION_PLAN_FAMILY_ORDER_IN_FLIGHT")

    current_active = tuple(
        item for item in current_rows if item.reservation.status is OrderReservationStatus.ACTIVE
    )
    current_cancelled = tuple(
        item for item in current_rows if item.reservation.status is OrderReservationStatus.CANCELLED
    )
    current_completed = tuple(
        item for item in current_rows if item.reservation.status is OrderReservationStatus.COMPLETED
    )
    if current_active:
        reason_codes.append("TRANSITION_PLAN_ORDER_IN_FLIGHT")
    terminal_incomplete = any(
        item.reservation.filled_quantity < item.reservation.quantity
        for item in (*current_cancelled, *current_completed)
    )
    if current_cancelled or terminal_incomplete:
        reason_codes.append("TRANSITION_PLAN_SUCCESSOR_REVIEW_REQUIRED")

    fills_known = history_complete and all(item.fills is not None for item in current_rows)
    if not fills_known:
        if current_rows:
            reason_codes.append("TRANSITION_PLAN_FILL_HISTORY_INCOMPLETE")
        filled_quantity: Decimal | None = None
        released_quantity: Decimal | None = None
        actual_fees_paid: Decimal | None = None
        fees_complete = False
    else:
        filled_quantity = _sum_quantities(
            tuple(fill.quantity for item in current_rows for fill in (item.fills or ()))
        )
        released_quantity = _sum_quantities(
            tuple(
                item.reservation.quantity - item.reservation.filled_quantity
                for item in current_cancelled
            )
        )
        fee_values = tuple(fill.actual_fee for item in current_rows for fill in (item.fills or ()))
        fees_complete = all(value is not None for value in fee_values)
        actual_fees_paid = (
            _sum_quantities(tuple(value for value in fee_values if value is not None))
            if fees_complete
            else None
        )

    if current_completed and filled_quantity is not None and filled_quantity < approved:
        reason_codes.append("TRANSITION_PLAN_SUCCESSOR_REVIEW_REQUIRED")

    if history_complete:
        in_flight_quantity = _sum_quantities(
            tuple(item.reservation.remaining_quantity for item in current_active)
        )
        reserved_buy_cash = (
            _sum_quantities(tuple(item.reservation.remaining_cash for item in current_active))
            if order.side == "buy"
            else Decimal("0")
        )
        released_buy_cash = (
            _sum_quantities(tuple(item.reservation.cash_released for item in current_cancelled))
            if order.side == "buy"
            else Decimal("0")
        )
        active_sell_quantity = in_flight_quantity if order.side == "sell" else Decimal("0")
        family_active = (*current_active, *related_active)
        family_fills_known = all(item.fills is not None for item in family_active)
        family_in_flight_quantity = (
            _sum_quantities(tuple(item.reservation.remaining_quantity for item in family_active))
            if family_fills_known
            else None
        )
    else:
        in_flight_quantity = None
        reserved_buy_cash = None
        released_buy_cash = None
        active_sell_quantity = None
        family_active = (*current_active, *related_active)
        family_in_flight_quantity = None

    remaining_quantity: Decimal | None = None
    unreserved_remaining_quantity: Decimal | None = None
    if filled_quantity is not None and in_flight_quantity is not None:
        if filled_quantity > approved_decimal:
            reason_codes.append("TRANSITION_PLAN_ORDER_OVERFILLED")
        else:
            remaining_quantity = approved_decimal - filled_quantity
            if in_flight_quantity > remaining_quantity:
                reason_codes.append("TRANSITION_PLAN_ACTIVE_HOLD_EXCEEDS_REMAINDER")
            else:
                unreserved_remaining_quantity = remaining_quantity - in_flight_quantity

    if (
        not history_complete
        or not fills_known
        or any(
            "MISMATCH" in code or "DUPLICATE" in code or "MULTIPLE" in code for code in reason_codes
        )
    ):
        outcome: PlanExecutionOutcome = "unknown"
    elif reason_codes:
        outcome = (
            "in_flight"
            if current_active
            else (
                "successor_required"
                if "TRANSITION_PLAN_SUCCESSOR_REVIEW_REQUIRED" in reason_codes
                else "blocked"
            )
        )
    elif remaining_quantity == Decimal("0"):
        outcome = "complete"
    else:
        outcome = "ready"

    can_preview = (
        outcome == "ready"
        and unreserved_remaining_quantity is not None
        and not current_rows
        and not matching_attempts
        and order.approved_quantity > 0
        and order.status != "blocked"
    )
    return PlanOrderExecutionProgress(
        revision_identity=identity,
        order=order,
        outcome=outcome,
        approved_quantity=approved,
        filled_quantity=filled_quantity,
        in_flight_quantity=in_flight_quantity,
        family_in_flight_quantity=family_in_flight_quantity,
        released_quantity=released_quantity,
        remaining_quantity=remaining_quantity,
        unreserved_remaining_quantity=unreserved_remaining_quantity,
        reserved_buy_cash=reserved_buy_cash,
        released_buy_cash=released_buy_cash,
        active_sell_quantity=active_sell_quantity,
        actual_fees_paid=actual_fees_paid,
        fees_complete=fees_complete,
        active_order_ids=tuple(item.reservation_id for item in current_active),
        family_active_order_ids=tuple(item.reservation_id for item in family_active),
        completed_order_ids=tuple(item.reservation_id for item in current_completed),
        cancelled_order_ids=tuple(item.reservation_id for item in current_cancelled),
        replay_order_id=replay_order_id,
        attempts=tuple(_attempt_progress(item) for item in current_rows),
        action_attempt_keys=tuple(item.binding.action_attempt_key for item in current_rows),
        predecessor_sells_settled=(
            predecessor_sells_settled
            if order.side == "buy" and "BUY_DEPENDS_ON_SETTLED_SALES" in order.reason_codes
            else None
        ),
        can_recover=replay_order_id is not None and history_complete and fills_known,
        can_preview=can_preview,
        can_cancel=(
            bool(current_active)
            and history_complete
            and all(item.fills is not None for item in current_active)
            and not any(
                "MISMATCH" in code or "DUPLICATE" in code or "MULTIPLE" in code
                for code in reason_codes
            )
        ),
        requires_successor="TRANSITION_PLAN_SUCCESSOR_REVIEW_REQUIRED" in reason_codes,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _attempt_progress(item: PlanExecutionReservation) -> PlanExecutionAttemptProgress:
    """Project the verified facts for one idempotent reservation attempt."""

    reservation = item.reservation
    fills = item.fills
    actual_fee_values = () if fills is None else tuple(fill.actual_fee for fill in fills)
    fees_complete = fills is not None and all(value is not None for value in actual_fee_values)
    fee_total = (
        _sum_quantities(tuple(value for value in actual_fee_values if value is not None))
        if fees_complete
        else None
    )
    status_by_reservation: dict[
        OrderReservationStatus, Literal["active", "completed", "cancelled"]
    ] = {
        OrderReservationStatus.ACTIVE: "active",
        OrderReservationStatus.COMPLETED: "completed",
        OrderReservationStatus.CANCELLED: "cancelled",
    }
    return PlanExecutionAttemptProgress(
        action_attempt_key=item.binding.action_attempt_key,
        reservation_id=item.reservation_id,
        status=status_by_reservation[reservation.status],
        reserved_quantity=reservation.quantity,
        filled_quantity=(
            _sum_quantities(tuple(fill.quantity for fill in fills)) if fills is not None else None
        ),
        gross_filled_value=(
            _sum_quantities(tuple(fill.gross_amount for fill in fills))
            if fills is not None
            else None
        ),
        remaining_quantity=reservation.remaining_quantity,
        remaining_cash_held=reservation.remaining_cash,
        cash_consumed=reservation.cash_consumed,
        cash_released=reservation.cash_released,
        actual_fees_paid=fee_total,
        fees_complete=fees_complete,
        fill_receipt_ids=tuple(fill.receipt_id for fill in fills or ()),
        trade_ids=tuple(fill.trade_id for fill in fills or ()),
    )


def _same_plan_order(
    left: PlanOrderExecutionBinding,
    identity: PlanRevisionExecutionIdentity,
    order: PlanOrderExecutionReference,
) -> bool:
    """Find one persisted action linked to the exact immutable plan-order line."""

    return (
        left.plan_id == identity.plan_id
        and left.plan_version == identity.version
        and left.revision_hash == identity.revision_hash
        and left.order_ordinal == order.ordinal
        and left.plan_order_binding_id == order.plan_order_binding_id
    )


def _reservation_binding_matches_order(
    binding: PlanOrderExecutionBinding,
    *,
    revision_identity: PlanRevisionExecutionIdentity,
    order: PlanOrderExecutionReference,
    revision_recorded_at: datetime,
) -> bool:
    """Verify one stored action still names the exact immutable plan-order facts."""

    return (
        binding.plan_id == revision_identity.plan_id
        and binding.family_id == revision_identity.family_id
        and binding.root_plan_id == revision_identity.root_plan_id
        and binding.plan_version == revision_identity.version
        and binding.revision_hash == revision_identity.revision_hash
        and binding.order_ordinal == order.ordinal
        and binding.plan_order_binding_id == order.plan_order_binding_id
        and binding.order_content_hash == order.order_content_hash
        and binding.account_id == revision_identity.account_id
        and binding.owner_user_id == revision_identity.owner_user_id
        and binding.asset_code == order.asset_code
        and binding.security_id == order.security_id
        and binding.asset_type == order.asset_type
        and binding.classification_content_hash == order.classification_content_hash
        and binding.side == order.side
        and binding.approved_quantity == order.approved_quantity
        and binding.approved_limit_price == order.approved_limit_price
        and binding.quantity_unit == order.quantity_unit
        and binding.money_unit == order.money_unit
        and binding.plan_expires_at == revision_identity.valid_until
        and revision_recorded_at == revision_identity.recorded_at
    )
