"""Pure economic preparation tests for simulated-order partial fills.

These tests do not represent an accepted external execution event. They verify
only exact fill economics against a frozen reservation and FeeV2 policy.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    SimulatedTradeIntent,
    SimulatedTradeSide,
    TradeFeeBreakdown,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
    OrderReservationRequest,
    reserve_order,
)
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillAccrual,
    OrderReservationFillEconomics,
    OrderReservationFillRequest,
    prepare_order_reservation_fill,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
ZERO = Decimal("0.00")
ZERO_SHARES = Decimal("0.000000")
ZERO_FEES = TradeFeeBreakdown(ZERO, ZERO, ZERO, ZERO, ZERO)


def _intent(
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    quantity: Decimal = Decimal("100.000000"),
    price: Decimal = Decimal("10.0000"),
    key: str = "fill-order-001",
) -> SimulatedTradeIntent:
    """Build a complete exact intent for reservation-fill unit tests."""

    return SimulatedTradeIntent(
        account_id=7,
        user_id=11,
        idempotency_key=key,
        side=side,
        security_id="SH.FILL.SECURITY",
        asset_code="600000.SH",
        asset_name="fill test security",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=quantity,
        price=price,
        reason="test-only partial fill economics",
        signal_id=None,
    )


def _fee_policy(
    *,
    min_commission: Decimal = Decimal("5"),
    commission_rate: Decimal = Decimal("0.0003"),
) -> SimulatedFeePolicyV2:
    """Build the same exact-case FeeV2 snapshot used by settlement tests."""

    schedule = ExecutionFeeSchedule(
        config_id=3,
        asset_type="equity",
        commission_rate_buy=commission_rate,
        commission_rate_sell=commission_rate,
        min_commission=min_commission,
        stamp_duty_rate=Decimal("0.001"),
        transfer_fee_rate=Decimal("0.00002"),
        min_transfer_fee=Decimal("0"),
        slippage_rate=Decimal("0.001"),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )
    cases = tuple(
        FeeTransactionCase(
            asset_type="equity",
            market="SH",
            board="MAIN",
            side=side,
            commission=FeeApplicability.APPLIES,
            transfer_fee=FeeApplicability.APPLIES,
            stamp_duty=FeeApplicability.APPLIES,
            slippage=FeeApplicability.APPLIES,
        )
        for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL)
    )
    start = AS_OF - timedelta(days=1)
    return SimulatedFeePolicyV2(
        fee_schedule_v1=schedule,
        policy_id="fill-test-fee-policy",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=start,
        valid_until=AS_OF + timedelta(days=30),
        recorded_at=start,
        transaction_cases=cases,
    )


def _reservation(
    intent: SimulatedTradeIntent,
    *,
    fee_policy: SimulatedFeePolicyV2 | None = None,
    fee_budget: Decimal = Decimal("100.00"),
) -> OrderReservation:
    """Reserve one order using a real Domain book and exact FeeV2 calculation."""

    policy = fee_policy or _fee_policy()
    request = OrderReservationRequest(
        account_id=intent.account_id,
        security_id=intent.security_id,
        idempotency_key=intent.idempotency_key,
        side=intent.side,
        quantity=intent.quantity,
        limit_price=intent.price,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        fee_budget=fee_budget if intent.side is SimulatedTradeSide.BUY else None,
    )
    book = OrderReservationBook(
        intent.account_id,
        intent.security_id,
        Decimal("1000000.00"),
        None,
        Decimal("1000000.000000"),
        (),
    )
    return reserve_order(book, request, policy, reserved_at=AS_OF).reservation


def _initial_accrual() -> OrderReservationFillAccrual:
    """Declare the exact no-prior-fill state instead of guessing unknown fees."""

    return OrderReservationFillAccrual(
        fill_count=0,
        cumulative_quantity=ZERO_SHARES,
        cumulative_gross=ZERO,
        cumulative_fees=ZERO_FEES,
    )


def _prepare(
    *,
    intent: SimulatedTradeIntent,
    reservation: OrderReservation,
    fee_policy: SimulatedFeePolicyV2,
    event_id: str,
    quantity: Decimal,
    price: Decimal,
    prior: OrderReservationFillAccrual | None = None,
    stored_intent_payload_hash: str | None = None,
    fill_occurred_at: datetime = AS_OF,
    close_order: bool = False,
) -> OrderReservationFillEconomics:
    """Call the fill economics boundary with the immutable stored intent hash."""

    return prepare_order_reservation_fill(
        OrderReservationFillRequest(
            fill_event_id=event_id,
            intent=intent,
            stored_intent_payload_hash=(
                intent.request_payload_hash
                if stored_intent_payload_hash is None
                else stored_intent_payload_hash
            ),
            reservation=reservation,
            fee_policy=fee_policy,
            fill_occurred_at=fill_occurred_at,
            quantity=quantity,
            price=price,
            prior=prior or _initial_accrual(),
            close_order=close_order,
        )
    )


def test_two_small_partial_fills_charge_minimum_commission_once() -> None:
    intent = _intent()
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy, fee_budget=Decimal("20.00"))

    first = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="broker-fill-001",
        quantity=Decimal("50.000000"),
        price=Decimal("10.0000"),
    )
    after_first = reservation.apply_fill(
        filled_quantity=first.quantity,
        cash_consumed=first.gross_amount + first.incremental_fees.total_fee,
    )
    second = _prepare(
        intent=intent,
        reservation=after_first,
        fee_policy=policy,
        event_id="broker-fill-002",
        quantity=Decimal("50.000000"),
        price=Decimal("10.0000"),
        prior=first.cumulative_state,
    )

    assert first.incremental_fees.commission == Decimal("5.00")
    assert second.incremental_fees.commission == Decimal("0.00")
    assert second.cumulative_state.cumulative_fees.commission == Decimal("5.00")
    assert second.cumulative_state.cumulative_gross == Decimal("1000.00")


def test_proportional_commission_delta_crosses_minimum_on_cumulative_gross() -> None:
    intent = _intent(quantity=Decimal("2000.000000"))
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)

    first = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="broker-fill-threshold-001",
        quantity=Decimal("1000.000000"),
        price=Decimal("10.0000"),
    )
    after_first = reservation.apply_fill(
        filled_quantity=first.quantity,
        cash_consumed=first.gross_amount + first.incremental_fees.total_fee,
    )
    second = _prepare(
        intent=intent,
        reservation=after_first,
        fee_policy=policy,
        event_id="broker-fill-threshold-002",
        quantity=Decimal("1000.000000"),
        price=Decimal("10.0000"),
        prior=first.cumulative_state,
    )

    assert first.incremental_fees.commission == Decimal("5.00")
    assert second.incremental_fees.commission == Decimal("1.00")
    assert second.cumulative_state.cumulative_fees.commission == Decimal("6.00")


@pytest.mark.parametrize(
    ("side", "limit_price", "fill_price", "error_code"),
    [
        (
            SimulatedTradeSide.BUY,
            Decimal("10.0000"),
            Decimal("10.0001"),
            "FILL_PRICE_ABOVE_BUY_LIMIT",
        ),
        (
            SimulatedTradeSide.SELL,
            Decimal("10.0000"),
            Decimal("9.9999"),
            "FILL_PRICE_BELOW_SELL_LIMIT",
        ),
    ],
)
def test_fill_price_must_respect_original_order_limit(
    side: SimulatedTradeSide,
    limit_price: Decimal,
    fill_price: Decimal,
    error_code: str,
) -> None:
    intent = _intent(side=side, price=limit_price)
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)

    with pytest.raises(ValueError) as raised:
        _prepare(
            intent=intent,
            reservation=reservation,
            fee_policy=policy,
            event_id=f"fill-limit-{side.value}",
            quantity=Decimal("10.000000"),
            price=fill_price,
        )

    assert getattr(raised.value, "code", None) == error_code


def test_fill_rejects_reservation_quantity_changed_without_changing_identity() -> None:
    intent = _intent(quantity=Decimal("100.000000"), price=Decimal("10.0000"))
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)
    altered = replace(
        reservation,
        quantity=Decimal("200.000000"),
        notional=Decimal("2000.00"),
        cash_reserved=Decimal("2100.00"),
    )
    assert altered.identity == reservation.identity

    with pytest.raises(ValueError) as raised:
        _prepare(
            intent=intent,
            reservation=altered,
            fee_policy=policy,
            event_id="fill-original-quantity-overrun",
            quantity=Decimal("150.000000"),
            price=Decimal("10.0000"),
        )

    assert getattr(raised.value, "code", None) == "FILL_RESERVATION_INTENT_MISMATCH"


def test_buy_fill_rejects_reservation_limit_changed_without_changing_identity() -> None:
    intent = _intent(quantity=Decimal("100.000000"), price=Decimal("10.0000"))
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)
    altered = replace(
        reservation,
        limit_price=Decimal("20.0000"),
        notional=Decimal("2000.00"),
        cash_reserved=Decimal("2100.00"),
    )
    assert altered.identity == reservation.identity

    with pytest.raises(ValueError) as raised:
        _prepare(
            intent=intent,
            reservation=altered,
            fee_policy=policy,
            event_id="buy-fill-original-limit-overrun",
            quantity=Decimal("10.000000"),
            price=Decimal("15.0000"),
        )

    assert getattr(raised.value, "code", None) == "FILL_RESERVATION_INTENT_MISMATCH"


def test_sell_fill_rejects_reservation_limit_changed_without_changing_identity() -> None:
    intent = _intent(
        side=SimulatedTradeSide.SELL,
        quantity=Decimal("100.000000"),
        price=Decimal("10.0000"),
    )
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)
    altered = replace(
        reservation,
        limit_price=Decimal("5.0000"),
        notional=Decimal("500.00"),
    )
    assert altered.identity == reservation.identity

    with pytest.raises(ValueError) as raised:
        _prepare(
            intent=intent,
            reservation=altered,
            fee_policy=policy,
            event_id="sell-fill-original-limit-underrun",
            quantity=Decimal("10.000000"),
            price=Decimal("6.0000"),
        )

    assert getattr(raised.value, "code", None) == "FILL_RESERVATION_INTENT_MISMATCH"


def test_fill_rejects_sell_reservation_fee_estimate_changed_from_frozen_policy() -> None:
    intent = _intent(
        side=SimulatedTradeSide.SELL,
        quantity=Decimal("1.000000"),
        price=Decimal("0.0100"),
    )
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)
    assert reservation.fee_estimate > reservation.notional
    altered = replace(
        reservation,
        fee_estimate=ZERO,
        cash_reserved=ZERO,
    )
    assert altered.identity == reservation.identity
    actual_fees = policy.calculate_for(
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        side=intent.side,
        amount=reservation.notional,
        as_of=reservation.reserved_at,
    )
    assert actual_fees.total_fee > altered.fee_estimate

    with pytest.raises(ValueError) as raised:
        _prepare(
            intent=intent,
            reservation=altered,
            fee_policy=policy,
            event_id="sell-fill-fee-reserve-understated",
            quantity=Decimal("1.000000"),
            price=Decimal("0.0100"),
        )

    assert getattr(raised.value, "code", None) == "FILL_RESERVATION_FEE_SNAPSHOT_MISMATCH"


def test_fill_may_be_smaller_than_the_order_quantity_step() -> None:
    intent = _intent(quantity=Decimal("100.000000"))
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)

    prepared = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="broker-fill-small-lot",
        quantity=Decimal("1.000000"),
        price=Decimal("10.0000"),
    )

    assert prepared.quantity == Decimal("1.000000")
    assert prepared.gross_amount == Decimal("10.00")


def test_fill_cannot_exceed_the_unfilled_reserved_quantity() -> None:
    intent = _intent(quantity=Decimal("100.000000"))
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)

    with pytest.raises(ValueError) as raised:
        _prepare(
            intent=intent,
            reservation=reservation,
            fee_policy=policy,
            event_id="broker-fill-overrun",
            quantity=Decimal("100.000001"),
            price=Decimal("10.0000"),
        )

    assert getattr(raised.value, "code", None) == "FILL_EXCEEDS_REMAINING_ORDER_QUANTITY"


@pytest.mark.parametrize(
    ("quantity", "price"),
    [
        (Decimal("NaN"), Decimal("10.0000")),
        (Decimal("Infinity"), Decimal("10.0000")),
        (Decimal("1.000000"), Decimal("NaN")),
        (Decimal("1.000000"), Decimal("Infinity")),
        (Decimal("1.0000001"), Decimal("10.0000")),
        (Decimal("1.000000"), Decimal("10.00001")),
    ],
)
def test_fill_rejects_unknown_nonfinite_or_unrepresentable_values(
    quantity: Decimal,
    price: Decimal,
) -> None:
    intent = _intent()
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)

    with pytest.raises(ValueError):
        _prepare(
            intent=intent,
            reservation=reservation,
            fee_policy=policy,
            event_id="broker-fill-invalid-value",
            quantity=quantity,
            price=price,
        )


def test_unknown_prior_fee_state_is_not_treated_as_zero() -> None:
    with pytest.raises(ValueError):
        OrderReservationFillAccrual(
            fill_count=1,
            cumulative_quantity=Decimal("1.000000"),
            cumulative_gross=Decimal("10.00"),
            cumulative_fees=None,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("cumulative_quantity", "cumulative_gross", "fees"),
    [
        (Decimal("1.000000"), Decimal("NaN"), ZERO_FEES),
        (
            Decimal("1.000000"),
            Decimal("10.00"),
            TradeFeeBreakdown(Decimal("Infinity"), ZERO, ZERO, ZERO, Decimal("Infinity")),
        ),
        (Decimal("1.000000"), Decimal("10.001"), ZERO_FEES),
    ],
)
def test_prior_accrual_rejects_nonfinite_and_unrepresentable_amounts(
    cumulative_quantity: Decimal,
    cumulative_gross: Decimal,
    fees: TradeFeeBreakdown,
) -> None:
    with pytest.raises(ValueError):
        OrderReservationFillAccrual(
            fill_count=1,
            cumulative_quantity=cumulative_quantity,
            cumulative_gross=cumulative_gross,
            cumulative_fees=fees,
        )


def test_prior_fee_components_must_match_the_same_frozen_policy() -> None:
    intent = _intent(quantity=Decimal("200.000000"))
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)
    inconsistent = OrderReservationFillAccrual(
        fill_count=1,
        cumulative_quantity=Decimal("50.000000"),
        cumulative_gross=Decimal("500.00"),
        cumulative_fees=TradeFeeBreakdown(
            Decimal("4.99"), Decimal("0.01"), Decimal("0.50"), Decimal("0.50"), Decimal("6.00")
        ),
    )

    with pytest.raises(ValueError) as raised:
        _prepare(
            intent=intent,
            reservation=reservation.apply_fill(
                filled_quantity=Decimal("50.000000"), cash_consumed=Decimal("506.01")
            ),
            fee_policy=policy,
            event_id="broker-fill-policy-mismatch",
            quantity=Decimal("10.000000"),
            price=Decimal("10.0000"),
            prior=inconsistent,
        )

    assert getattr(raised.value, "code", None) == "PRIOR_FEE_STATE_POLICY_MISMATCH"


def test_fill_payload_hash_is_stable_and_binds_economics_to_event_identity() -> None:
    intent = _intent()
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)
    first = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="stable-broker-fill-001",
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
    )
    exact_retry = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="stable-broker-fill-001",
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
    )
    changed_economics = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="stable-broker-fill-001",
        quantity=Decimal("9.000000"),
        price=Decimal("10.0000"),
    )
    changed_event = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="stable-broker-fill-002",
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
    )
    changed_event_time = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="stable-broker-fill-001",
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
        fill_occurred_at=AS_OF + timedelta(minutes=1),
    )
    close_order = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="stable-broker-fill-001",
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
        close_order=True,
    )

    assert first.payload_hash == exact_retry.payload_hash
    assert first.payload_hash != changed_economics.payload_hash
    assert first.payload_hash != changed_event.payload_hash
    assert first.payload_hash != changed_event_time.payload_hash
    assert first.payload_hash != close_order.payload_hash
    assert first.close_order is False
    assert close_order.close_order is True


def test_fill_payload_hash_excludes_mutable_cumulative_accrual() -> None:
    intent = _intent()
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy, fee_budget=Decimal("20.00"))
    prior_fill = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="different-earlier-fill",
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
        fill_occurred_at=AS_OF,
    )
    reservation_after_prior = reservation.apply_fill(
        filled_quantity=prior_fill.quantity,
        cash_consumed=prior_fill.gross_amount + prior_fill.incremental_fees.total_fee,
    )

    from_initial = _prepare(
        intent=intent,
        reservation=reservation,
        fee_policy=policy,
        event_id="stable-current-event",
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
        fill_occurred_at=AS_OF + timedelta(seconds=1),
    )
    after_other_fill = _prepare(
        intent=intent,
        reservation=reservation_after_prior,
        fee_policy=policy,
        event_id="stable-current-event",
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
        prior=prior_fill.cumulative_state,
        fill_occurred_at=AS_OF + timedelta(seconds=1),
    )

    assert from_initial.payload_hash == after_other_fill.payload_hash
    assert from_initial.prior != after_other_fill.prior


def test_fill_rejects_a_stored_intent_hash_or_fee_policy_mismatch() -> None:
    intent = _intent()
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)

    with pytest.raises(ValueError) as intent_error:
        _prepare(
            intent=intent,
            reservation=reservation,
            fee_policy=policy,
            event_id="fill-intent-hash-mismatch",
            quantity=Decimal("1.000000"),
            price=Decimal("10.0000"),
            stored_intent_payload_hash="0" * 64,
        )
    assert getattr(intent_error.value, "code", None) == "FILL_INTENT_SNAPSHOT_MISMATCH"

    changed_policy = _fee_policy(min_commission=Decimal("6"))
    with pytest.raises(ValueError) as fee_error:
        _prepare(
            intent=intent,
            reservation=reservation,
            fee_policy=changed_policy,
            event_id="fill-fee-policy-mismatch",
            quantity=Decimal("1.000000"),
            price=Decimal("10.0000"),
        )
    assert getattr(fee_error.value, "code", None) == "FILL_RESERVATION_POLICY_MISMATCH"


def test_fill_arithmetic_is_independent_of_low_ambient_decimal_precision() -> None:
    intent = _intent(quantity=Decimal("2000.000000"), price=Decimal("11.0000"))
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)

    with localcontext() as context:
        context.prec = 2
        prepared = _prepare(
            intent=intent,
            reservation=reservation,
            fee_policy=policy,
            event_id="low-context-fill",
            quantity=Decimal("1000.000000"),
            price=Decimal("10.1234"),
        )

    assert prepared.gross_amount == Decimal("10123.40")
    assert prepared.cumulative_state.cumulative_gross == Decimal("10123.40")


@pytest.mark.parametrize("close_order", [False, True])
def test_fill_request_requires_an_aware_event_time(close_order: bool) -> None:
    intent = _intent()
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)

    with pytest.raises(ValueError):
        _prepare(
            intent=intent,
            reservation=reservation,
            fee_policy=policy,
            event_id="naive-event-time",
            quantity=Decimal("1.000000"),
            price=Decimal("10.0000"),
            fill_occurred_at=datetime(2026, 10, 16, 2, 0),
            close_order=close_order,
        )


def test_fill_event_time_cannot_precede_the_reserved_order() -> None:
    intent = _intent()
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)

    with pytest.raises(ValueError) as raised:
        _prepare(
            intent=intent,
            reservation=reservation,
            fee_policy=policy,
            event_id="event-before-reservation",
            quantity=Decimal("1.000000"),
            price=Decimal("10.0000"),
            fill_occurred_at=AS_OF - timedelta(seconds=1),
        )

    assert getattr(raised.value, "code", None) == "FILL_TIME_PRECEDES_RESERVATION"


@pytest.mark.parametrize("terminal_status", ["completed", "cancelled"])
def test_new_fill_event_is_rejected_for_a_terminal_order(terminal_status: str) -> None:
    intent = _intent()
    policy = _fee_policy()
    reservation = _reservation(intent, fee_policy=policy)
    if terminal_status == "completed":
        final_gross = reservation.notional
        final_fees = policy.calculate_for(
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            side=intent.side,
            amount=final_gross,
            as_of=reservation.reserved_at,
        )
        terminal = reservation.apply_fill(
            filled_quantity=reservation.quantity,
            cash_consumed=final_gross + final_fees.total_fee,
        )
    else:
        terminal = reservation.release_remaining()

    with pytest.raises(ValueError) as raised:
        _prepare(
            intent=intent,
            reservation=terminal,
            fee_policy=policy,
            event_id=f"terminal-order-fill-{terminal_status}",
            quantity=Decimal("1.000000"),
            price=Decimal("10.0000"),
        )

    assert getattr(raised.value, "code", None) == "FILL_RESERVATION_NOT_ACTIVE"
