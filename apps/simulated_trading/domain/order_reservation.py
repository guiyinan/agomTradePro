"""Pure exact-value contracts for simulated-order cash and sellable-share holds.

Callers provide already-qualified source values. This module does not read
accounts, establish freshness, lock rows, or write the trade ledger. It accepts
sellable quantity only; total and pending T+1 position quantity are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from enum import StrEnum

from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_primitives import (
    _MAX_IDEMPOTENCY_LENGTH,
    _decimal_numeric_text,
    _hash_payload,
    _require_hash,
    _require_token,
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedSettlementContractError,
    SimulatedTradeSide,
)

_MONEY_SCALE = 2
_SHARE_SCALE = 6
_MONEY_QUANTUM = Decimal("0.01")
_ZERO_MONEY = Decimal("0.00")
_ZERO_SHARES = Decimal("0.000000")


class OrderReservationError(SimulatedSettlementContractError):
    """Raised when a reservation is unknown, conflicting, or unaffordable."""

    def __init__(self, code: str) -> None:
        """Expose a stable machine-readable reservation error code."""

        self.code = code
        super().__init__(code)


class OrderReservationStatus(StrEnum):
    """Lifecycle states for one immutable reservation record."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def _need(condition: bool, code: str) -> None:
    """Raise one exact domain error when a reservation invariant is false."""

    if not condition:
        raise OrderReservationError(code)


def _utc(value: object, field_name: str) -> datetime:
    """Validate an aware datetime and normalize its instant to UTC."""

    if type(value) is not datetime:
        raise OrderReservationError(f"{field_name.upper()}_INVALID")
    if value.tzinfo is None:
        raise OrderReservationError(f"{field_name.upper()}_INVALID")
    try:
        if value.utcoffset() is None:
            raise OrderReservationError(f"{field_name.upper()}_INVALID")
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise OrderReservationError(f"{field_name.upper()}_INVALID") from error


def _units(value: Decimal, scale: int, field_name: str) -> int:
    """Convert a validated fixed-scale Decimal into exact integer units."""

    parts = value.as_tuple()
    exponent = parts.exponent
    if not isinstance(exponent, int):
        raise OrderReservationError(f"{field_name.upper()}_PRECISION_INVALID")
    coefficient = int("".join(str(digit) for digit in parts.digits))
    power = exponent + scale
    scaled_coefficient: int
    if power >= 0:
        scaled_coefficient = coefficient * 10**power
    else:
        divisor: int = 10 ** (-power)
        scaled_coefficient, remainder = divmod(coefficient, divisor)
        _need(remainder == 0, f"{field_name.upper()}_PRECISION_INVALID")
    return (-1 if parts.sign else 1) * scaled_coefficient


def _decimal(value: int, scale: int) -> Decimal:
    """Build a Decimal from integer ledger units without context rounding."""

    text = str(abs(value))
    return Decimal((int(value < 0), tuple(int(char) for char in text), -scale))


def _sum(values: tuple[Decimal, ...], scale: int, field_name: str) -> Decimal:
    """Sum fixed-scale money or quantity using exact integer arithmetic."""

    result = _decimal(sum(_units(value, scale, field_name) for value in values), scale)
    return (
        validate_ledger_money(result, field_name, allow_zero=True)
        if scale == _MONEY_SCALE
        else validate_ledger_quantity(result, field_name, allow_zero=True)
    )


def _add(left: Decimal, right: Decimal, scale: int, field_name: str) -> Decimal:
    """Add exact nonnegative ledger values without ambient Decimal context."""

    result = _decimal(_units(left, scale, field_name) + _units(right, scale, field_name), scale)
    return (
        validate_ledger_money(result, field_name, allow_zero=True)
        if scale == _MONEY_SCALE
        else validate_ledger_quantity(result, field_name, allow_zero=True)
    )


def _subtract(left: Decimal, right: Decimal, scale: int, field_name: str) -> Decimal:
    """Subtract exact ledger values after rejecting a negative result."""

    units = _units(left, scale, field_name) - _units(right, scale, field_name)
    _need(units >= 0, f"{field_name.upper()}_NEGATIVE")
    result = _decimal(units, scale)
    return (
        validate_ledger_money(result, field_name, allow_zero=True)
        if scale == _MONEY_SCALE
        else validate_ledger_quantity(result, field_name, allow_zero=True)
    )


def _notional(
    quantity: Decimal,
    price: Decimal,
    *,
    allow_zero: bool = False,
) -> Decimal:
    """Calculate cent-rounded limit notional under settlement's half-even rule."""

    try:
        with localcontext() as context:
            context.prec = 80
            amount = (quantity * price).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, OverflowError) as error:
        raise OrderReservationError("ORDER_NOTIONAL_UNREPRESENTABLE") from error
    return validate_ledger_money(amount, "order_notional", allow_zero=allow_zero)


@dataclass(frozen=True, slots=True)
class OrderReservationIdentity:
    """Bind one idempotency key to its account, security, and request digest."""

    account_id: int
    security_id: str
    idempotency_key: str
    request_payload_hash: str

    def __post_init__(self) -> None:
        """Require complete, bounded order identity fields."""

        _need(type(self.account_id) is int and self.account_id > 0, "RESERVATION_ACCOUNT_INVALID")
        _require_token(self.security_id, "security_id")
        _require_token(self.idempotency_key, "idempotency_key", max_length=_MAX_IDEMPOTENCY_LENGTH)
        _require_hash(self.request_payload_hash, "request_payload_hash")


@dataclass(frozen=True, slots=True)
class OrderReservationRequest:
    """Exact BUY or SELL limit-order inputs used to derive one reservation."""

    account_id: int
    security_id: str
    idempotency_key: str
    side: SimulatedTradeSide
    quantity: Decimal
    limit_price: Decimal
    asset_type: str
    market: str
    board: str
    fee_budget: Decimal | None

    def __post_init__(self) -> None:
        """Reject missing dimensions, ledger precision loss, and absent BUY budget."""

        _need(type(self.account_id) is int and self.account_id > 0, "RESERVATION_ACCOUNT_INVALID")
        _require_token(self.security_id, "security_id")
        _require_token(self.idempotency_key, "idempotency_key", max_length=_MAX_IDEMPOTENCY_LENGTH)
        _need(type(self.side) is SimulatedTradeSide, "ORDER_SIDE_INVALID")
        for field_name, value in (
            ("asset_type", self.asset_type),
            ("market", self.market),
            ("board", self.board),
        ):
            _require_token(value, field_name)
        validate_ledger_quantity(self.quantity, "quantity", allow_zero=False)
        validate_ledger_price(self.limit_price, "limit_price", allow_zero=False)
        if self.side is SimulatedTradeSide.BUY:
            if self.fee_budget is None:
                raise OrderReservationError("BUY_FEE_BUDGET_REQUIRED")
            validate_ledger_money(self.fee_budget, "fee_budget", allow_zero=True)
        else:
            _need(self.fee_budget is None, "SELL_FEE_BUDGET_NOT_APPLICABLE")

    @property
    def notional(self) -> Decimal:
        """Return the exact cent-rounded order notional at the supplied limit."""

        self.__post_init__()
        return _notional(self.quantity, self.limit_price)

    def identity(self, *, fee_policy_hash: str) -> OrderReservationIdentity:
        """Build stable identity from the request economics and exact FeeV2 hash."""

        self.__post_init__()
        _require_hash(fee_policy_hash, "fee_policy_hash")
        payload_hash = _hash_payload(
            {
                "schema": "simulated-order-reservation-request.v1",
                "account_id": self.account_id,
                "security_id": self.security_id,
                "side": self.side.value,
                "quantity": _decimal_numeric_text(self.quantity),
                "limit_price": _decimal_numeric_text(self.limit_price),
                "asset_type": self.asset_type,
                "market": self.market,
                "board": self.board,
                "fee_budget": (
                    _decimal_numeric_text(self.fee_budget) if self.fee_budget is not None else None
                ),
                "fee_policy_hash": fee_policy_hash,
            }
        )
        return OrderReservationIdentity(
            self.account_id,
            self.security_id,
            self.idempotency_key,
            payload_hash,
        )


@dataclass(frozen=True, slots=True)
class OrderReservation:
    """Immutable hold accounting for one accepted order and its later fills."""

    identity: OrderReservationIdentity
    side: SimulatedTradeSide
    quantity: Decimal
    limit_price: Decimal
    notional: Decimal
    fee_estimate: Decimal
    fee_budget: Decimal | None
    cash_reserved: Decimal
    shares_reserved: Decimal
    reserved_at: datetime
    status: OrderReservationStatus = OrderReservationStatus.ACTIVE
    filled_quantity: Decimal = _ZERO_SHARES
    cash_consumed: Decimal = _ZERO_MONEY
    shares_consumed: Decimal = _ZERO_SHARES
    cash_released: Decimal = _ZERO_MONEY
    shares_released: Decimal = _ZERO_SHARES

    def __post_init__(self) -> None:
        """Reconcile exact hold buckets, fill progress, and terminal lifecycle."""

        _need(type(self.identity) is OrderReservationIdentity, "RESERVATION_IDENTITY_INVALID")
        self.identity.__post_init__()
        _need(type(self.side) is SimulatedTradeSide, "ORDER_SIDE_INVALID")
        _need(type(self.status) is OrderReservationStatus, "RESERVATION_STATUS_INVALID")
        validate_ledger_quantity(self.quantity, "quantity", allow_zero=False)
        validate_ledger_price(self.limit_price, "limit_price", allow_zero=False)
        validate_ledger_money(self.notional, "notional", allow_zero=False)
        _need(
            self.notional == _notional(self.quantity, self.limit_price),
            "RESERVATION_NOTIONAL_MISMATCH",
        )
        for name, value in (
            ("fee_estimate", self.fee_estimate),
            ("cash_reserved", self.cash_reserved),
            ("cash_consumed", self.cash_consumed),
            ("cash_released", self.cash_released),
        ):
            validate_ledger_money(value, name, allow_zero=True)
        for name, value in (
            ("shares_reserved", self.shares_reserved),
            ("filled_quantity", self.filled_quantity),
            ("shares_consumed", self.shares_consumed),
            ("shares_released", self.shares_released),
        ):
            validate_ledger_quantity(value, name, allow_zero=True)
        object.__setattr__(self, "reserved_at", _utc(self.reserved_at, "reserved_at"))

        if self.side is SimulatedTradeSide.BUY:
            if self.fee_budget is None:
                raise OrderReservationError("BUY_FEE_BUDGET_REQUIRED")
            validate_ledger_money(self.fee_budget, "fee_budget", allow_zero=True)
            _need(self.fee_budget >= self.fee_estimate, "BUY_FEE_BUDGET_INSUFFICIENT")
            expected_cash = _add(self.notional, self.fee_budget, _MONEY_SCALE, "cash_reserved")
            _need(
                self.cash_reserved == expected_cash and self.shares_reserved == _ZERO_SHARES,
                "BUY_RESERVATION_AMOUNT_INVALID",
            )
            _need(
                self.shares_consumed == _ZERO_SHARES == self.shares_released,
                "BUY_SHARE_HOLD_INVALID",
            )
        else:
            _need(self.fee_budget is None, "SELL_FEE_BUDGET_NOT_APPLICABLE")
            deficit = max(
                _units(self.fee_estimate, _MONEY_SCALE, "fee_estimate")
                - _units(self.notional, _MONEY_SCALE, "notional"),
                0,
            )
            _need(
                self.cash_reserved == _decimal(deficit, _MONEY_SCALE), "SELL_CASH_DEFICIT_INVALID"
            )
            _need(
                self.shares_reserved == self.quantity
                and self.shares_consumed == self.filled_quantity,
                "SELL_SHARE_HOLD_INVALID",
            )

        cash_left = (
            _units(self.cash_reserved, _MONEY_SCALE, "cash_reserved")
            - _units(self.cash_consumed, _MONEY_SCALE, "cash_consumed")
            - _units(self.cash_released, _MONEY_SCALE, "cash_released")
        )
        shares_left = (
            _units(self.shares_reserved, _SHARE_SCALE, "shares_reserved")
            - _units(self.shares_consumed, _SHARE_SCALE, "shares_consumed")
            - _units(self.shares_released, _SHARE_SCALE, "shares_released")
        )
        _need(cash_left >= 0 and shares_left >= 0, "RESERVATION_RESOURCE_OVERCONSUMED")
        _need(self.filled_quantity <= self.quantity, "RESERVATION_OVERFILLED")
        if self.status is OrderReservationStatus.ACTIVE:
            _need(self.filled_quantity < self.quantity, "ACTIVE_RESERVATION_ALREADY_FILLED")
            _need(
                cash_left > 0 if self.side is SimulatedTradeSide.BUY else shares_left > 0,
                "ACTIVE_RESERVATION_UNFUNDED",
            )
            _need(
                self.cash_released == _ZERO_MONEY and self.shares_released == _ZERO_SHARES,
                "ACTIVE_RESERVATION_HAS_RELEASED_RESOURCES",
            )
        elif self.status is OrderReservationStatus.COMPLETED:
            _need(
                self.filled_quantity == self.quantity and cash_left == 0 and shares_left == 0,
                "COMPLETED_RESERVATION_INVALID",
            )
        else:
            _need(
                self.filled_quantity < self.quantity and cash_left == 0 and shares_left == 0,
                "CANCELLED_RESERVATION_INVALID",
            )

    @property
    def remaining_cash(self) -> Decimal:
        """Return cash still held after prior fills and releases."""

        self.__post_init__()
        return _decimal(
            _units(self.cash_reserved, _MONEY_SCALE, "cash")
            - _units(self.cash_consumed, _MONEY_SCALE, "cash")
            - _units(self.cash_released, _MONEY_SCALE, "cash"),
            _MONEY_SCALE,
        )

    @property
    def remaining_buy_notional(self) -> Decimal | None:
        """Return remaining active BUY shares valued at their accepted limit price.

        Cash holds include fee budget and cash actually consumed by prior fills;
        neither amount identifies the unfilled order's gross exposure. Filled
        shares are already represented by the account position ledger.
        """

        self.__post_init__()
        if self.side is not SimulatedTradeSide.BUY:
            return None
        if self.status is not OrderReservationStatus.ACTIVE:
            return _ZERO_MONEY
        remaining_quantity = _subtract(
            self.quantity,
            self.filled_quantity,
            _SHARE_SCALE,
            "remaining_buy_quantity",
        )
        return _notional(remaining_quantity, self.limit_price, allow_zero=True)

    @property
    def remaining_shares(self) -> Decimal:
        """Return shares still held after prior fills and releases."""

        self.__post_init__()
        return _decimal(
            _units(self.shares_reserved, _SHARE_SCALE, "shares")
            - _units(self.shares_consumed, _SHARE_SCALE, "shares")
            - _units(self.shares_released, _SHARE_SCALE, "shares"),
            _SHARE_SCALE,
        )

    def apply_fill(
        self, *, filled_quantity: Decimal, cash_consumed: Decimal, close_order: bool = False
    ) -> OrderReservation:
        """Consume held resources for one fill and release terminal remainder.

        For SELL, ``cash_consumed`` is only additional account cash required
        after limit proceeds, not gross fees. The caller must apply this hold
        transition together with authoritative ledger changes in one transaction.
        """

        self.__post_init__()
        _need(type(close_order) is bool, "CLOSE_ORDER_FLAG_INVALID")
        _need(self.status is OrderReservationStatus.ACTIVE, "ORDER_RESERVATION_TERMINAL")
        validate_ledger_quantity(filled_quantity, "filled_quantity", allow_zero=False)
        validate_ledger_money(cash_consumed, "cash_consumed", allow_zero=True)
        _need(self.side is not SimulatedTradeSide.BUY or cash_consumed > 0, "BUY_FILL_CASH_INVALID")
        next_filled = _add(self.filled_quantity, filled_quantity, _SHARE_SCALE, "filled_quantity")
        _need(next_filled <= self.quantity, "RESERVATION_OVERFILLED")
        _need(
            self.side is not SimulatedTradeSide.SELL or filled_quantity <= self.remaining_shares,
            "SELL_FILL_EXCEEDS_HELD_SHARES",
        )
        next_cash = _add(self.cash_consumed, cash_consumed, _MONEY_SCALE, "cash_consumed")
        _need(next_cash <= self.cash_reserved, "FILL_EXCEEDS_HELD_CASH")
        next_shares = next_filled if self.side is SimulatedTradeSide.SELL else self.shares_consumed
        full = next_filled == self.quantity
        terminal = full or close_order
        cash_released = self.cash_released
        shares_released = self.shares_released
        status = OrderReservationStatus.ACTIVE
        if terminal:
            cash_released = _add(
                cash_released,
                _subtract(self.cash_reserved, next_cash, _MONEY_SCALE, "cash_remaining"),
                _MONEY_SCALE,
                "cash_released",
            )
            shares_released = _add(
                shares_released,
                _subtract(self.shares_reserved, next_shares, _SHARE_SCALE, "shares_remaining"),
                _SHARE_SCALE,
                "shares_released",
            )
            status = OrderReservationStatus.COMPLETED if full else OrderReservationStatus.CANCELLED
        elif self.side is SimulatedTradeSide.BUY and next_cash == self.cash_reserved:
            raise OrderReservationError("PARTIAL_BUY_FILL_EXHAUSTS_REMAINING_HOLD")
        return replace(
            self,
            status=status,
            filled_quantity=next_filled,
            cash_consumed=next_cash,
            shares_consumed=next_shares,
            cash_released=cash_released,
            shares_released=shares_released,
        )

    def release_remaining(self) -> OrderReservation:
        """Release remaining resources once; repeat terminal cancellation safely."""

        self.__post_init__()
        if self.status is not OrderReservationStatus.ACTIVE:
            return self
        return replace(
            self,
            status=OrderReservationStatus.CANCELLED,
            cash_released=_add(
                self.cash_released, self.remaining_cash, _MONEY_SCALE, "cash_released"
            ),
            shares_released=_add(
                self.shares_released, self.remaining_shares, _SHARE_SCALE, "shares_released"
            ),
        )


@dataclass(frozen=True, slots=True)
class OrderReservationBook:
    """Source-known account/security snapshot plus its persisted reservation set.

    Book cash is not withdrawable cash. Sellable shares are not total position
    quantity. After a fill, the caller must atomically update the ledger and
    reservation before using a refreshed book to admit another order.
    """

    account_id: int
    security_id: str
    book_cash: Decimal | None
    withdrawable_cash: Decimal | None
    sellable_shares: Decimal | None
    reservations: tuple[OrderReservation, ...]

    def __post_init__(self) -> None:
        """Validate exact source amounts, account-scoped keys, and over-holds."""

        _need(type(self.account_id) is int and self.account_id > 0, "RESERVATION_ACCOUNT_INVALID")
        _require_token(self.security_id, "security_id")
        if self.book_cash is not None:
            validate_ledger_money(self.book_cash, "book_cash", allow_zero=True)
        if self.withdrawable_cash is not None:
            validate_ledger_money(self.withdrawable_cash, "withdrawable_cash", allow_zero=True)
        if self.sellable_shares is not None:
            validate_ledger_quantity(self.sellable_shares, "sellable_shares", allow_zero=True)
        _need(type(self.reservations) is tuple, "RESERVATION_BOOK_ROWS_INVALID")
        keys: set[str] = set()
        for row in self.reservations:
            _need(type(row) is OrderReservation, "RESERVATION_BOOK_ROWS_INVALID")
            row.__post_init__()
            _need(row.identity.account_id == self.account_id, "RESERVATION_BOOK_ACCOUNT_MISMATCH")
            _need(row.identity.idempotency_key not in keys, "RESERVATION_BOOK_DUPLICATE_ORDER_KEY")
            keys.add(row.identity.idempotency_key)
        cash_holds = tuple(
            row.remaining_cash
            for row in self.reservations
            if row.status is OrderReservationStatus.ACTIVE
        )
        share_holds = tuple(
            row.remaining_shares
            for row in self.reservations
            if row.status is OrderReservationStatus.ACTIVE
            and row.identity.security_id == self.security_id
            and row.side is SimulatedTradeSide.SELL
        )
        if self.book_cash is not None:
            _need(
                _units(
                    _sum(cash_holds, _MONEY_SCALE, "active_held_cash"), _MONEY_SCALE, "book_cash"
                )
                <= _units(self.book_cash, _MONEY_SCALE, "book_cash"),
                "BOOK_CASH_OVERHELD",
            )
        if self.sellable_shares is not None:
            _need(
                _units(
                    _sum(share_holds, _SHARE_SCALE, "active_held_shares"),
                    _SHARE_SCALE,
                    "sellable_shares",
                )
                <= _units(self.sellable_shares, _SHARE_SCALE, "sellable_shares"),
                "SELLABLE_SHARES_OVERHELD",
            )

    @property
    def active_held_cash(self) -> Decimal:
        """Sum remaining active cash holds across this account."""

        self.__post_init__()
        return _sum(
            tuple(
                row.remaining_cash
                for row in self.reservations
                if row.status is OrderReservationStatus.ACTIVE
            ),
            _MONEY_SCALE,
            "active_held_cash",
        )

    @property
    def active_held_shares(self) -> Decimal:
        """Sum remaining active SELL holds for this security only."""

        self.__post_init__()
        return _sum(
            tuple(
                row.remaining_shares
                for row in self.reservations
                if row.status is OrderReservationStatus.ACTIVE
                and row.identity.security_id == self.security_id
                and row.side is SimulatedTradeSide.SELL
            ),
            _SHARE_SCALE,
            "active_held_shares",
        )

    @property
    def available_cash(self) -> Decimal | None:
        """Return known book cash minus active holds, or preserve unknown as None."""

        self.__post_init__()
        return (
            None
            if self.book_cash is None
            else _subtract(self.book_cash, self.active_held_cash, _MONEY_SCALE, "available_cash")
        )

    @property
    def available_shares(self) -> Decimal | None:
        """Return known sellable shares minus active holds for this security."""

        self.__post_init__()
        return (
            None
            if self.sellable_shares is None
            else _subtract(
                self.sellable_shares, self.active_held_shares, _SHARE_SCALE, "available_shares"
            )
        )

    def find_reservation(self, *, idempotency_key: str) -> OrderReservation | None:
        """Find an existing account-scoped order key without guessing a match."""

        self.__post_init__()
        _require_token(idempotency_key, "idempotency_key", max_length=_MAX_IDEMPOTENCY_LENGTH)
        return next(
            (row for row in self.reservations if row.identity.idempotency_key == idempotency_key),
            None,
        )

    def append_reservation(self, reservation: OrderReservation) -> OrderReservationBook:
        """Return a new source snapshot with one order hold appended."""

        self.__post_init__()
        _need(type(reservation) is OrderReservation, "RESERVATION_INVALID")
        reservation.__post_init__()
        _need(
            reservation.identity.account_id == self.account_id, "RESERVATION_BOOK_ACCOUNT_MISMATCH"
        )
        _need(
            self.find_reservation(idempotency_key=reservation.identity.idempotency_key) is None,
            "RESERVATION_BOOK_DUPLICATE_ORDER_KEY",
        )
        return replace(self, reservations=(*self.reservations, reservation))


@dataclass(frozen=True, slots=True)
class OrderReservationResult:
    """Return the next immutable snapshot and whether an exact retry replayed."""

    book: OrderReservationBook
    reservation: OrderReservation
    replayed: bool

    def __post_init__(self) -> None:
        """Ensure the result contains its exact row and a literal replay flag."""

        _need(type(self.book) is OrderReservationBook, "RESERVATION_RESULT_BOOK_INVALID")
        _need(type(self.reservation) is OrderReservation, "RESERVATION_RESULT_ROW_INVALID")
        _need(type(self.replayed) is bool, "RESERVATION_RESULT_REPLAY_FLAG_INVALID")
        _need(
            self.book.find_reservation(idempotency_key=self.reservation.identity.idempotency_key)
            == self.reservation,
            "RESERVATION_RESULT_ROW_MISMATCH",
        )


def reserve_order(
    book: OrderReservationBook,
    request: OrderReservationRequest,
    fee_policy: SimulatedFeePolicyV2,
    *,
    reserved_at: datetime,
) -> OrderReservationResult:
    """Reserve known resources from an exact request and FeeV2 estimate.

    BUY holds notional plus an explicit fee budget that covers the FeeV2
    estimate. SELL holds known sellable shares and only the fee deficit above
    cent-rounded limit proceeds. No source amount is inferred from another.
    """

    _need(type(book) is OrderReservationBook, "RESERVATION_BOOK_INVALID")
    book.__post_init__()
    _need(type(request) is OrderReservationRequest, "RESERVATION_REQUEST_INVALID")
    request.__post_init__()
    _need(type(fee_policy) is SimulatedFeePolicyV2, "FEE_POLICY_V2_REQUIRED")
    fee_policy.__post_init__()
    _need(request.account_id == book.account_id, "RESERVATION_BOOK_ACCOUNT_MISMATCH")
    cutoff = _utc(reserved_at, "reserved_at")
    identity = request.identity(fee_policy_hash=fee_policy.content_hash)
    existing = book.find_reservation(idempotency_key=request.idempotency_key)
    if existing is not None:
        _need(existing.identity == identity, "ORDER_IDEMPOTENCY_CONFLICT")
        return OrderReservationResult(book, existing, True)
    _need(request.security_id == book.security_id, "RESERVATION_BOOK_SECURITY_MISMATCH")

    fee_policy.validate_at(cutoff)
    notional = request.notional
    fees = fee_policy.calculate_for(
        asset_type=request.asset_type,
        market=request.market,
        board=request.board,
        side=request.side,
        amount=notional,
        as_of=cutoff,
    )
    fee_estimate = validate_ledger_money(fees.total_fee, "fee_estimate", allow_zero=True)
    if request.side is SimulatedTradeSide.BUY:
        if request.fee_budget is None:
            raise OrderReservationError("BUY_FEE_BUDGET_REQUIRED")
        _need(request.fee_budget >= fee_estimate, "BUY_FEE_BUDGET_INSUFFICIENT")
        cash_reserved = _add(notional, request.fee_budget, _MONEY_SCALE, "cash_reserved")
        available_cash = book.available_cash
        if available_cash is None:
            raise OrderReservationError("BOOK_CASH_UNKNOWN")
        _need(cash_reserved <= available_cash, "INSUFFICIENT_AVAILABLE_CASH")
        shares_reserved = _ZERO_SHARES
    else:
        available_shares = book.available_shares
        if available_shares is None:
            raise OrderReservationError("SELLABLE_SHARES_UNKNOWN")
        _need(request.quantity <= available_shares, "INSUFFICIENT_AVAILABLE_SHARES")
        deficit = max(
            _units(fee_estimate, _MONEY_SCALE, "fee_estimate")
            - _units(notional, _MONEY_SCALE, "notional"),
            0,
        )
        cash_reserved = _decimal(deficit, _MONEY_SCALE)
        if cash_reserved > _ZERO_MONEY:
            available_cash = book.available_cash
            if available_cash is None:
                raise OrderReservationError("BOOK_CASH_UNKNOWN_FOR_SELL_FEE_DEFICIT")
            _need(cash_reserved <= available_cash, "INSUFFICIENT_AVAILABLE_CASH")
        shares_reserved = request.quantity

    reservation = OrderReservation(
        identity=identity,
        side=request.side,
        quantity=request.quantity,
        limit_price=request.limit_price,
        notional=notional,
        fee_estimate=fee_estimate,
        fee_budget=request.fee_budget,
        cash_reserved=cash_reserved,
        shares_reserved=shares_reserved,
        reserved_at=cutoff,
    )
    next_book = book.append_reservation(reservation)
    return OrderReservationResult(next_book, reservation, False)


__all__: tuple[str, ...] = (
    "OrderReservation",
    "OrderReservationBook",
    "OrderReservationError",
    "OrderReservationIdentity",
    "OrderReservationRequest",
    "OrderReservationResult",
    "OrderReservationStatus",
    "reserve_order",
)
