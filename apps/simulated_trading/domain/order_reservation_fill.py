"""Prepare exact economics for partial fills of an existing simulated order.

This pure-domain boundary does not establish that a fill occurred, authorize a
source, consume a reservation, update an account, or create a trade. A caller
must persist the returned economics atomically with its independently verified
fill event and existing ledger writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_primitives import (
    _decimal_numeric_text,
    _hash_payload,
    _require_aware,
    _require_hash,
    _require_token,
    _utc_text,
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
    TradeFeeBreakdown,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationError,
    OrderReservationIdentity,
    OrderReservationRequest,
    OrderReservationStatus,
)

_MONEY_QUANTUM = Decimal("0.01")
_SHARE_QUANTUM = Decimal("0.000001")
_ZERO_MONEY = Decimal("0.00")
_ZERO_SHARES = Decimal("0.000000")
_MAX_FILL_EVENT_ID_LENGTH = 128
_MAX_FILL_COUNT = 2_147_483_647


def _need(condition: bool, code: str) -> None:
    """Raise one stable domain error when a fill invariant is not satisfied."""

    if not condition:
        raise OrderReservationError(code)


def _fee_values(fees: TradeFeeBreakdown) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Return fee components in the canonical policy order."""

    return (fees.commission, fees.transfer_fee, fees.stamp_duty, fees.slippage, fees.total_fee)


def _validated_fees(fees: object, field_name: str) -> TradeFeeBreakdown:
    """Require a complete finite cent-valued fee breakdown, never unknown-as-zero."""

    _need(type(fees) is TradeFeeBreakdown, f"{field_name.upper()}_UNKNOWN")
    assert isinstance(fees, TradeFeeBreakdown)
    for component, value in zip(
        ("commission", "transfer_fee", "stamp_duty", "slippage", "total_fee"),
        _fee_values(fees),
        strict=True,
    ):
        validate_ledger_money(value, f"{field_name}.{component}", allow_zero=True)
    _need(
        _sum_money(
            (fees.commission, fees.transfer_fee, fees.stamp_duty, fees.slippage),
            f"{field_name}.components",
        )
        == fees.total_fee,
        f"{field_name.upper()}_TOTAL_MISMATCH",
    )
    return fees


def _sum_money(values: tuple[Decimal, ...], field_name: str) -> Decimal:
    """Sum validated ledger money using context-independent precision."""

    try:
        with localcontext() as context:
            context.prec = 80
            total = sum(values, _ZERO_MONEY)
    except (InvalidOperation, OverflowError) as error:
        raise OrderReservationError(f"{field_name.upper()}_UNREPRESENTABLE") from error
    return validate_ledger_money(total, field_name, allow_zero=True)


def _add_money(left: Decimal, right: Decimal, field_name: str) -> Decimal:
    """Add cent-rounded amounts without consulting the ambient Decimal context."""

    try:
        with localcontext() as context:
            context.prec = 80
            total = left + right
    except (InvalidOperation, OverflowError) as error:
        raise OrderReservationError(f"{field_name.upper()}_UNREPRESENTABLE") from error
    return validate_ledger_money(total, field_name, allow_zero=True)


def _add_quantity(left: Decimal, right: Decimal, field_name: str) -> Decimal:
    """Add six-decimal share quantities under a bounded local context."""

    try:
        with localcontext() as context:
            context.prec = 80
            total = left + right
    except (InvalidOperation, OverflowError) as error:
        raise OrderReservationError(f"{field_name.upper()}_UNREPRESENTABLE") from error
    return validate_ledger_quantity(total, field_name, allow_zero=True)


def _fill_gross(quantity: Decimal, price: Decimal) -> Decimal:
    """Calculate one fill's ledger notional using half-even cent rounding."""

    try:
        with localcontext() as context:
            context.prec = 80
            gross = (quantity * price).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, OverflowError) as error:
        raise OrderReservationError("FILL_GROSS_UNREPRESENTABLE") from error
    return validate_ledger_money(gross, "fill_gross", allow_zero=False)


def _subtract_fee_components(
    after: TradeFeeBreakdown,
    before: TradeFeeBreakdown,
) -> TradeFeeBreakdown:
    """Return nonnegative per-component increases under one frozen FeeV2 policy."""

    deltas: list[Decimal] = []
    for name, after_value, before_value in zip(
        ("commission", "transfer_fee", "stamp_duty", "slippage"),
        _fee_values(after)[:4],
        _fee_values(before)[:4],
        strict=True,
    ):
        try:
            with localcontext() as context:
                context.prec = 80
                delta = after_value - before_value
        except (InvalidOperation, OverflowError) as error:
            raise OrderReservationError(f"FILL_{name.upper()}_DELTA_INVALID") from error
        _need(delta >= _ZERO_MONEY, f"FILL_{name.upper()}_DELTA_NEGATIVE")
        deltas.append(validate_ledger_money(delta, f"incremental_{name}", allow_zero=True))
    values = (deltas[0], deltas[1], deltas[2], deltas[3])
    return TradeFeeBreakdown(
        commission=values[0],
        transfer_fee=values[1],
        stamp_duty=values[2],
        slippage=values[3],
        total_fee=_sum_money(values, "incremental_total_fee"),
    )


@dataclass(frozen=True, slots=True)
class OrderReservationFillAccrual:
    """Explicitly known cumulative fill quantity, gross, and FeeV2 components."""

    fill_count: int
    cumulative_quantity: Decimal
    cumulative_gross: Decimal
    cumulative_fees: TradeFeeBreakdown

    def __post_init__(self) -> None:
        """Reject unknown values and require zero only for an explicit initial state."""

        _need(
            type(self.fill_count) is int and 0 <= self.fill_count <= _MAX_FILL_COUNT,
            "FILL_COUNT_INVALID",
        )
        validate_ledger_quantity(
            self.cumulative_quantity, "cumulative_fill_quantity", allow_zero=True
        )
        validate_ledger_money(self.cumulative_gross, "cumulative_fill_gross", allow_zero=True)
        fees = _validated_fees(self.cumulative_fees, "cumulative_fees")
        if self.fill_count == 0:
            _need(
                self.cumulative_quantity == _ZERO_SHARES
                and self.cumulative_gross == _ZERO_MONEY
                and fees
                == TradeFeeBreakdown(
                    _ZERO_MONEY, _ZERO_MONEY, _ZERO_MONEY, _ZERO_MONEY, _ZERO_MONEY
                ),
                "INITIAL_FILL_ACCRUAL_MUST_BE_EXPLICIT_ZERO",
            )
        else:
            _need(
                self.cumulative_quantity > _ZERO_SHARES and self.cumulative_gross > _ZERO_MONEY,
                "PRIOR_FILL_ACCRUAL_UNKNOWN",
            )


def _calculate_fill_accrual(
    *,
    intent: SimulatedTradeIntent,
    reservation: OrderReservation,
    fee_policy: SimulatedFeePolicyV2,
    quantity: Decimal,
    price: Decimal,
    prior: OrderReservationFillAccrual,
) -> tuple[Decimal, OrderReservationFillAccrual, TradeFeeBreakdown]:
    """Recompute one fill's gross and FeeV2 cumulative accrual from typed inputs.

    This shared arithmetic leaf deliberately does not decide whether a parent
    reservation is active or whether ``prior`` equals its current prefix. The
    normal new-fill request enforces those live-state rules; the historical
    chain validator independently proves its ordered prior rows.
    """

    _need(type(intent) is SimulatedTradeIntent, "FILL_INTENT_INVALID")
    intent.__post_init__()
    _need(type(reservation) is OrderReservation, "FILL_RESERVATION_INVALID")
    reservation.__post_init__()
    _need(type(fee_policy) is SimulatedFeePolicyV2, "FILL_FEE_POLICY_INVALID")
    fee_policy.__post_init__()
    fee_policy.validate_at(reservation.reserved_at)
    _need(type(prior) is OrderReservationFillAccrual, "FILL_PRIOR_STATE_UNKNOWN")
    prior.__post_init__()
    validate_ledger_quantity(quantity, "fill_quantity", allow_zero=False)
    validate_ledger_price(price, "fill_price", allow_zero=False)

    if prior.fill_count == 0:
        prior_fees = TradeFeeBreakdown(
            _ZERO_MONEY, _ZERO_MONEY, _ZERO_MONEY, _ZERO_MONEY, _ZERO_MONEY
        )
    else:
        prior_fees = fee_policy.calculate_for(
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            side=intent.side,
            amount=prior.cumulative_gross,
            as_of=reservation.reserved_at,
        )
        _need(
            prior.cumulative_fees == prior_fees,
            "PRIOR_FEE_STATE_POLICY_MISMATCH",
        )

    gross_amount = _fill_gross(quantity, price)
    cumulative_gross = _add_money(prior.cumulative_gross, gross_amount, "cumulative_fill_gross")
    cumulative_quantity = _add_quantity(
        prior.cumulative_quantity, quantity, "cumulative_fill_quantity"
    )
    cumulative_fees = fee_policy.calculate_for(
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        side=intent.side,
        amount=cumulative_gross,
        as_of=reservation.reserved_at,
    )
    incremental_fees = _subtract_fee_components(cumulative_fees, prior_fees)
    next_state = OrderReservationFillAccrual(
        fill_count=prior.fill_count + 1,
        cumulative_quantity=cumulative_quantity,
        cumulative_gross=cumulative_gross,
        cumulative_fees=cumulative_fees,
    )
    return gross_amount, next_state, incremental_fees


@dataclass(frozen=True, slots=True)
class OrderReservationFillRequest:
    """Bind one explicit fill event to its stored order, intent, and FeeV2 snapshot."""

    fill_event_id: str
    intent: SimulatedTradeIntent
    stored_intent_payload_hash: str
    reservation: OrderReservation
    fee_policy: SimulatedFeePolicyV2
    fill_occurred_at: datetime
    quantity: Decimal
    price: Decimal
    prior: OrderReservationFillAccrual
    close_order: bool

    def __post_init__(self) -> None:
        """Validate frozen identities, exact fill fields, and the known prior state."""

        _require_token(
            self.fill_event_id,
            "fill_event_id",
            max_length=_MAX_FILL_EVENT_ID_LENGTH,
        )
        _need(type(self.intent) is SimulatedTradeIntent, "FILL_INTENT_INVALID")
        self.intent.__post_init__()
        _need(type(self.reservation) is OrderReservation, "FILL_RESERVATION_INVALID")
        self.reservation.__post_init__()
        _need(type(self.fee_policy) is SimulatedFeePolicyV2, "FILL_FEE_POLICY_INVALID")
        self.fee_policy.__post_init__()
        self.fee_policy.validate_at(self.reservation.reserved_at)
        _need(type(self.prior) is OrderReservationFillAccrual, "FILL_PRIOR_STATE_UNKNOWN")
        self.prior.__post_init__()
        _need(type(self.close_order) is bool, "FILL_CLOSE_ORDER_FLAG_INVALID")
        _require_aware(self.fill_occurred_at, "fill_occurred_at")
        _require_hash(self.stored_intent_payload_hash, "stored_intent_payload_hash")
        _need(
            self.stored_intent_payload_hash == self.intent.request_payload_hash,
            "FILL_INTENT_SNAPSHOT_MISMATCH",
        )
        validate_ledger_quantity(self.quantity, "fill_quantity", allow_zero=False)
        validate_ledger_price(self.price, "fill_price", allow_zero=False)
        _need(
            self.fill_occurred_at >= self.reservation.reserved_at,
            "FILL_TIME_PRECEDES_RESERVATION",
        )
        _need(
            self.reservation.status is OrderReservationStatus.ACTIVE,
            "FILL_RESERVATION_NOT_ACTIVE",
        )
        _need(
            self.prior.cumulative_quantity == self.reservation.filled_quantity,
            "PRIOR_FILL_QUANTITY_MISMATCH",
        )
        _need(
            (self.prior.fill_count == 0) == (self.reservation.filled_quantity == _ZERO_SHARES),
            "PRIOR_FILL_COUNT_MISMATCH",
        )
        expected_request = OrderReservationRequest(
            account_id=self.intent.account_id,
            security_id=self.intent.security_id,
            idempotency_key=self.intent.idempotency_key,
            side=self.intent.side,
            quantity=self.intent.quantity,
            limit_price=self.intent.price,
            asset_type=self.intent.asset_type,
            market=self.intent.market,
            board=self.intent.board,
            fee_budget=self.reservation.fee_budget,
        )
        _need(
            self.reservation.side is expected_request.side
            and self.reservation.quantity == expected_request.quantity
            and self.reservation.limit_price == expected_request.limit_price
            and self.reservation.notional == expected_request.notional,
            "FILL_RESERVATION_INTENT_MISMATCH",
        )
        expected_identity = expected_request.identity(fee_policy_hash=self.fee_policy.content_hash)
        _need(
            self.reservation.identity == expected_identity,
            "FILL_RESERVATION_POLICY_MISMATCH",
        )
        expected_fees = self.fee_policy.calculate_for(
            asset_type=self.intent.asset_type,
            market=self.intent.market,
            board=self.intent.board,
            side=self.intent.side,
            amount=expected_request.notional,
            as_of=self.reservation.reserved_at,
        )
        _need(
            self.reservation.fee_estimate == expected_fees.total_fee,
            "FILL_RESERVATION_FEE_SNAPSHOT_MISMATCH",
        )
        remaining_quantity = _quantity_difference(
            self.reservation.quantity,
            self.reservation.filled_quantity,
            "remaining_order_quantity",
        )
        _need(
            self.quantity <= remaining_quantity,
            "FILL_EXCEEDS_REMAINING_ORDER_QUANTITY",
        )
        if self.intent.side is SimulatedTradeSide.BUY:
            _need(self.price <= self.reservation.limit_price, "FILL_PRICE_ABOVE_BUY_LIMIT")
        else:
            _need(self.price >= self.reservation.limit_price, "FILL_PRICE_BELOW_SELL_LIMIT")


def _quantity_difference(left: Decimal, right: Decimal, field_name: str) -> Decimal:
    """Subtract validated share values without ambient-context rounding."""

    try:
        with localcontext() as context:
            context.prec = 80
            difference = left - right
    except (InvalidOperation, OverflowError) as error:
        raise OrderReservationError(f"{field_name.upper()}_INVALID") from error
    _need(difference >= _ZERO_SHARES, f"{field_name.upper()}_NEGATIVE")
    return validate_ledger_quantity(difference, field_name, allow_zero=True)


def _payload_for_economics(
    *,
    fill_event_id: str,
    identity: OrderReservationIdentity,
    user_id: int,
    intent_payload_hash: str,
    fee_policy_hash: str,
    side: SimulatedTradeSide,
    asset_code: str,
    asset_type: str,
    market: str,
    board: str,
    limit_price: Decimal,
    quantity: Decimal,
    price: Decimal,
    fill_occurred_at: datetime,
    close_order: bool,
) -> dict[str, object]:
    """Build the immutable fill-request hash, excluding mutable accrual state."""

    return {
        "schema": "simulated-order-reservation-fill.v1",
        "fill_event_id": fill_event_id,
        "account_id": identity.account_id,
        "user_id": user_id,
        "security_id": identity.security_id,
        "idempotency_key": identity.idempotency_key,
        "reservation_request_payload_hash": identity.request_payload_hash,
        "intent_payload_hash": intent_payload_hash,
        "fee_policy_hash": fee_policy_hash,
        "side": side.value,
        "asset_code": asset_code,
        "asset_type": asset_type,
        "market": market,
        "board": board,
        "limit_price": _decimal_numeric_text(limit_price),
        "fill_quantity": _decimal_numeric_text(quantity),
        "fill_price": _decimal_numeric_text(price),
        "fill_occurred_at": _utc_text(fill_occurred_at),
        "close_order": close_order,
    }


@dataclass(frozen=True, slots=True)
class OrderReservationFillEconomics:
    """Immutable economic result ready for a later atomic persistence layer."""

    fill_event_id: str
    reservation_identity: OrderReservationIdentity
    user_id: int
    intent_payload_hash: str
    fee_policy_hash: str
    side: SimulatedTradeSide
    asset_code: str
    asset_type: str
    market: str
    board: str
    limit_price: Decimal
    fill_occurred_at: datetime
    close_order: bool
    quantity: Decimal
    price: Decimal
    gross_amount: Decimal
    prior: OrderReservationFillAccrual
    cumulative_state: OrderReservationFillAccrual
    incremental_fees: TradeFeeBreakdown
    payload_hash: str

    def __post_init__(self) -> None:
        """Revalidate economics and seal the immutable fill request identity."""

        _require_token(
            self.fill_event_id,
            "fill_event_id",
            max_length=_MAX_FILL_EVENT_ID_LENGTH,
        )
        _need(type(self.reservation_identity) is OrderReservationIdentity, "FILL_IDENTITY_INVALID")
        self.reservation_identity.__post_init__()
        _need(type(self.user_id) is int and self.user_id > 0, "FILL_USER_INVALID")
        _require_hash(self.intent_payload_hash, "intent_payload_hash")
        _require_hash(self.fee_policy_hash, "fee_policy_hash")
        _need(type(self.side) is SimulatedTradeSide, "FILL_SIDE_INVALID")
        for field_name, value in (
            ("asset_code", self.asset_code),
            ("asset_type", self.asset_type),
            ("market", self.market),
            ("board", self.board),
        ):
            _require_token(value, field_name)
        validate_ledger_price(self.limit_price, "limit_price", allow_zero=False)
        _require_aware(self.fill_occurred_at, "fill_occurred_at")
        _need(type(self.close_order) is bool, "FILL_CLOSE_ORDER_FLAG_INVALID")
        validate_ledger_quantity(self.quantity, "fill_quantity", allow_zero=False)
        validate_ledger_price(self.price, "fill_price", allow_zero=False)
        _need(
            (
                self.price <= self.limit_price
                if self.side is SimulatedTradeSide.BUY
                else self.price >= self.limit_price
            ),
            "FILL_RESULT_LIMIT_MISMATCH",
        )
        validate_ledger_money(self.gross_amount, "fill_gross", allow_zero=False)
        _need(
            self.gross_amount == _fill_gross(self.quantity, self.price),
            "FILL_RESULT_GROSS_MISMATCH",
        )
        self.prior.__post_init__()
        self.cumulative_state.__post_init__()
        fees = _validated_fees(self.incremental_fees, "incremental_fees")
        _need(
            self.prior.fill_count < _MAX_FILL_COUNT
            and self.cumulative_state.fill_count == self.prior.fill_count + 1,
            "FILL_RESULT_COUNT_MISMATCH",
        )
        _need(
            self.cumulative_state.cumulative_quantity
            == _add_quantity(
                self.prior.cumulative_quantity, self.quantity, "result_cumulative_quantity"
            ),
            "FILL_RESULT_QUANTITY_MISMATCH",
        )
        _need(
            self.cumulative_state.cumulative_gross
            == _add_money(
                self.prior.cumulative_gross, self.gross_amount, "result_cumulative_gross"
            ),
            "FILL_RESULT_GROSS_MISMATCH",
        )
        _need(
            self.cumulative_state.cumulative_fees
            == TradeFeeBreakdown(
                commission=_add_money(
                    self.prior.cumulative_fees.commission,
                    fees.commission,
                    "result_cumulative_commission",
                ),
                transfer_fee=_add_money(
                    self.prior.cumulative_fees.transfer_fee,
                    fees.transfer_fee,
                    "result_cumulative_transfer_fee",
                ),
                stamp_duty=_add_money(
                    self.prior.cumulative_fees.stamp_duty,
                    fees.stamp_duty,
                    "result_cumulative_stamp_duty",
                ),
                slippage=_add_money(
                    self.prior.cumulative_fees.slippage,
                    fees.slippage,
                    "result_cumulative_slippage",
                ),
                total_fee=_add_money(
                    self.prior.cumulative_fees.total_fee,
                    fees.total_fee,
                    "result_cumulative_total_fee",
                ),
            ),
            "FILL_RESULT_FEES_MISMATCH",
        )
        payload_hash = _hash_payload(
            _payload_for_economics(
                fill_event_id=self.fill_event_id,
                identity=self.reservation_identity,
                user_id=self.user_id,
                intent_payload_hash=self.intent_payload_hash,
                fee_policy_hash=self.fee_policy_hash,
                side=self.side,
                asset_code=self.asset_code,
                asset_type=self.asset_type,
                market=self.market,
                board=self.board,
                limit_price=self.limit_price,
                quantity=self.quantity,
                price=self.price,
                fill_occurred_at=self.fill_occurred_at,
                close_order=self.close_order,
            )
        )
        _need(self.payload_hash == payload_hash, "FILL_PAYLOAD_HASH_MISMATCH")


def prepare_order_reservation_fill(
    request: OrderReservationFillRequest,
) -> OrderReservationFillEconomics:
    """Calculate one exact partial fill against its order and frozen FeeV2 state.

    The caller must provide a stable source event ID and the immutable stored
    intent hash. Prior gross and component fees are required explicitly; zero is
    accepted only as the declared no-fill initial accrual. This calculation
    returns economics only and does not mark the reservation or account as
    updated.
    """

    _need(type(request) is OrderReservationFillRequest, "FILL_REQUEST_INVALID")
    request.__post_init__()
    prior = request.prior
    intent = request.intent
    policy = request.fee_policy
    gross_amount, next_state, incremental_fees = _calculate_fill_accrual(
        intent=intent,
        reservation=request.reservation,
        fee_policy=policy,
        quantity=request.quantity,
        price=request.price,
        prior=prior,
    )
    payload = _payload_for_economics(
        fill_event_id=request.fill_event_id,
        identity=request.reservation.identity,
        user_id=intent.user_id,
        intent_payload_hash=intent.request_payload_hash,
        fee_policy_hash=policy.content_hash,
        side=intent.side,
        asset_code=intent.asset_code,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        limit_price=request.reservation.limit_price,
        quantity=request.quantity,
        price=request.price,
        fill_occurred_at=request.fill_occurred_at,
        close_order=request.close_order,
    )
    return OrderReservationFillEconomics(
        fill_event_id=request.fill_event_id,
        reservation_identity=request.reservation.identity,
        user_id=intent.user_id,
        intent_payload_hash=intent.request_payload_hash,
        fee_policy_hash=policy.content_hash,
        side=intent.side,
        asset_code=intent.asset_code,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        limit_price=request.reservation.limit_price,
        fill_occurred_at=request.fill_occurred_at,
        close_order=request.close_order,
        quantity=request.quantity,
        price=request.price,
        gross_amount=gross_amount,
        prior=prior,
        cumulative_state=next_state,
        incremental_fees=incremental_fees,
        payload_hash=_hash_payload(payload),
    )


__all__: tuple[str, ...] = (
    "OrderReservationFillAccrual",
    "OrderReservationFillEconomics",
    "OrderReservationFillRequest",
    "prepare_order_reservation_fill",
)
