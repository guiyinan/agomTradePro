"""Pure-domain contracts for exact simulated-order resource reservations."""

from __future__ import annotations

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
    SimulatedTradeIntentValidationError,
    SimulatedTradeSide,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
    OrderReservationError,
    OrderReservationRequest,
    OrderReservationResult,
    OrderReservationStatus,
    reserve_order,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


def _fee_policy(*, minimum_commission: Decimal = Decimal("0.50")) -> SimulatedFeePolicyV2:
    """Build an explicit, exact V2 fee policy for the unit boundary."""

    schedule = ExecutionFeeSchedule(
        config_id=71,
        asset_type="equity",
        commission_rate_buy=Decimal("0.001"),
        commission_rate_sell=Decimal("0.001"),
        min_commission=minimum_commission,
        stamp_duty_rate=Decimal("0"),
        transfer_fee_rate=Decimal("0"),
        min_transfer_fee=Decimal("0"),
        slippage_rate=Decimal("0"),
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
    return SimulatedFeePolicyV2(
        fee_schedule_v1=schedule,
        policy_id="reservation-test-fees",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=AS_OF - timedelta(days=2),
        valid_until=AS_OF + timedelta(days=2),
        recorded_at=AS_OF - timedelta(days=3),
        transaction_cases=cases,
    )


def _book(
    *,
    book_cash: Decimal | None = Decimal("1000.00"),
    withdrawable_cash: Decimal | None = None,
    sellable_shares: Decimal | None = Decimal("100"),
    reservations: tuple[OrderReservation, ...] = (),
    security_id: str = "SH.600000",
) -> OrderReservationBook:
    """Build one explicit source snapshot and its already persisted holds."""

    return OrderReservationBook(
        account_id=9,
        security_id=security_id,
        book_cash=book_cash,
        withdrawable_cash=withdrawable_cash,
        sellable_shares=sellable_shares,
        reservations=reservations,
    )


def _request(
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    quantity: Decimal = Decimal("10"),
    limit_price: Decimal = Decimal("10.00"),
    fee_budget: Decimal | None = Decimal("0.50"),
    idempotency_key: str = "order-one",
    security_id: str = "SH.600000",
) -> OrderReservationRequest:
    """Build one exact request; no account or asset defaults are inferred."""

    return OrderReservationRequest(
        account_id=9,
        security_id=security_id,
        idempotency_key=idempotency_key,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        asset_type="equity",
        market="SH",
        board="MAIN",
        fee_budget=fee_budget,
    )


def _reserve(
    book: OrderReservationBook,
    request: OrderReservationRequest,
    *,
    policy: SimulatedFeePolicyV2 | None = None,
) -> OrderReservationResult:
    """Call the domain operation with a known UTC reservation cutoff."""

    return reserve_order(
        book,
        request,
        _fee_policy() if policy is None else policy,
        reserved_at=AS_OF,
    )


def test_unknown_cash_and_withdrawable_cash_are_not_replaced_with_zero_or_book_cash() -> None:
    unknown_cash = _book(book_cash=None, withdrawable_cash=None)

    assert unknown_cash.available_cash is None
    assert unknown_cash.withdrawable_cash is None
    with pytest.raises(OrderReservationError) as error:
        _reserve(unknown_cash, _request())
    assert error.value.code == "BOOK_CASH_UNKNOWN"
    assert unknown_cash.reservations == ()

    known_book_only = _book(book_cash=Decimal("100.00"), withdrawable_cash=None)
    assert known_book_only.available_cash == Decimal("100.00")
    assert known_book_only.withdrawable_cash is None

    known_zero_cash = _book(book_cash=Decimal("0.00"))
    assert known_zero_cash.available_cash == Decimal("0.00")
    with pytest.raises(OrderReservationError) as zero_error:
        _reserve(known_zero_cash, _request())
    assert zero_error.value.code == "INSUFFICIENT_AVAILABLE_CASH"


@pytest.mark.parametrize(
    "invalid_cash",
    (
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("1.001"),
        Decimal("10000000000000.00"),
    ),
)
def test_book_rejects_negative_nonfinite_or_unrepresentable_cash(invalid_cash: Decimal) -> None:
    with pytest.raises(SimulatedTradeIntentValidationError):
        _book(book_cash=invalid_cash)


def test_request_rejects_share_precision_beyond_the_ledger_column() -> None:
    with pytest.raises(SimulatedTradeIntentValidationError):
        _request(quantity=Decimal("1.0000001"))


def test_exact_trailing_zero_scales_match_existing_ledger_quantization_contract() -> None:
    book = _book(book_cash=Decimal("10.000"))
    request = _request(
        quantity=Decimal("1.0000000"),
        limit_price=Decimal("2.00000"),
        fee_budget=Decimal("0.500"),
    )

    result = _reserve(book, request)

    assert result.reservation.notional == Decimal("2.00")
    assert result.reservation.quantity == Decimal("1.0000000")
    assert result.reservation.shares_reserved == Decimal("0.000000")
    assert result.reservation.cash_reserved == Decimal("2.500")
    assert result.book.available_cash == Decimal("7.500")


def test_sell_freezes_exact_trailing_zero_quantity_as_sellable_shares() -> None:
    book = _book(
        book_cash=Decimal("0.00"),
        sellable_shares=Decimal("2.0000000"),
    )
    request = _request(
        side=SimulatedTradeSide.SELL,
        quantity=Decimal("1.0000000"),
        limit_price=Decimal("2.00000"),
        fee_budget=None,
    )

    result = _reserve(book, request)

    assert result.reservation.quantity == Decimal("1.0000000")
    assert result.reservation.shares_reserved == Decimal("1.0000000")
    assert result.book.available_shares == Decimal("1.0000000")
    assert result.reservation.cash_reserved == Decimal("0.00")


def test_unknown_sellable_quantity_blocks_sell_without_treating_it_as_zero() -> None:
    book = _book(book_cash=Decimal("0.00"), sellable_shares=None)
    request = _request(
        side=SimulatedTradeSide.SELL,
        fee_budget=None,
    )

    assert book.available_shares is None
    with pytest.raises(OrderReservationError) as error:
        _reserve(book, request)
    assert error.value.code == "SELLABLE_SHARES_UNKNOWN"
    assert book.reservations == ()


def test_sell_uses_only_source_sellable_quantity_not_total_or_pending_shares() -> None:
    # The reservation API deliberately has no total-position or pending-T+1 input.
    # A caller must provide the independently known sellable amount.
    book = _book(book_cash=Decimal("0.00"), sellable_shares=Decimal("8"))
    request = _request(
        side=SimulatedTradeSide.SELL,
        quantity=Decimal("9"),
        fee_budget=None,
    )

    assert book.available_shares == Decimal("8.000000")
    with pytest.raises(OrderReservationError) as error:
        _reserve(book, request)
    assert error.value.code == "INSUFFICIENT_AVAILABLE_SHARES"


def test_buy_requires_explicit_fee_budget_covering_the_exact_fee_v2_estimate() -> None:
    book = _book(book_cash=Decimal("1000.00"))
    request = _request(fee_budget=Decimal("0.49"))

    with pytest.raises(OrderReservationError) as error:
        _reserve(book, request)

    assert error.value.code == "BUY_FEE_BUDGET_INSUFFICIENT"
    assert book.reservations == ()


def test_zero_cash_sell_is_allowed_when_limit_proceeds_cover_exact_fees() -> None:
    book = _book(book_cash=Decimal("0.00"), sellable_shares=Decimal("10"))
    request = _request(side=SimulatedTradeSide.SELL, fee_budget=None)

    result = _reserve(book, request)

    assert result.reservation.fee_estimate == Decimal("0.50")
    assert result.reservation.cash_reserved == Decimal("0.00")
    assert result.reservation.shares_reserved == Decimal("10.000000")
    assert result.book.available_cash == Decimal("0.00")
    assert result.book.available_shares == Decimal("0.000000")
    assert result.book.withdrawable_cash is None


def test_sell_reserves_only_the_net_fee_deficit_over_limit_proceeds() -> None:
    expensive_policy = _fee_policy(minimum_commission=Decimal("150.00"))
    request = _request(side=SimulatedTradeSide.SELL, fee_budget=None)

    with pytest.raises(OrderReservationError) as error:
        _reserve(_book(book_cash=Decimal("49.99")), request, policy=expensive_policy)
    assert error.value.code == "INSUFFICIENT_AVAILABLE_CASH"

    result = _reserve(_book(book_cash=Decimal("50.00")), request, policy=expensive_policy)
    assert result.reservation.notional == Decimal("100.00")
    assert result.reservation.fee_estimate == Decimal("150.00")
    assert result.reservation.cash_reserved == Decimal("50.00")
    assert result.reservation.shares_reserved == Decimal("10.000000")
    assert result.book.available_cash == Decimal("0.00")


def test_competing_buy_holds_reduce_available_book_cash_before_admitting_next_order() -> None:
    first = _reserve(
        _book(book_cash=Decimal("150.00")),
        _request(idempotency_key="first", fee_budget=Decimal("1.00")),
    )

    assert first.reservation.cash_reserved == Decimal("101.00")
    assert first.book.active_held_cash == Decimal("101.00")
    assert first.book.available_cash == Decimal("49.00")

    second_request = _request(
        idempotency_key="second",
        quantity=Decimal("5"),
        fee_budget=Decimal("0.50"),
    )
    with pytest.raises(OrderReservationError) as error:
        _reserve(first.book, second_request)
    assert error.value.code == "INSUFFICIENT_AVAILABLE_CASH"
    assert len(first.book.reservations) == 1


def test_exact_idempotent_replay_returns_same_hold_and_changed_payload_conflicts() -> None:
    first = _reserve(_book(book_cash=Decimal("500.00")), _request())

    replay = _reserve(first.book, _request())

    assert replay.replayed is True
    assert replay.reservation == first.reservation
    assert replay.book == first.book
    assert replay.book.active_held_cash == first.book.active_held_cash

    changed = _request(quantity=Decimal("11"))
    with pytest.raises(OrderReservationError) as error:
        _reserve(first.book, changed)
    assert error.value.code == "ORDER_IDEMPOTENCY_CONFLICT"

    changed_security = _request(security_id="SH.600001")
    with pytest.raises(OrderReservationError) as security_error:
        _reserve(first.book, changed_security)
    assert security_error.value.code == "ORDER_IDEMPOTENCY_CONFLICT"


def test_fee_policy_snapshot_is_part_of_order_replay_identity() -> None:
    book = _book(book_cash=Decimal("500.00"))
    first = _reserve(book, _request(), policy=_fee_policy())

    with pytest.raises(OrderReservationError) as error:
        _reserve(
            first.book,
            _request(),
            policy=_fee_policy(minimum_commission=Decimal("0.75")),
        )
    assert error.value.code == "ORDER_IDEMPOTENCY_CONFLICT"


def test_partial_sell_fill_then_cancel_conserves_held_shares_and_is_terminal() -> None:
    result = _reserve(
        _book(book_cash=Decimal("0.00"), sellable_shares=Decimal("20")),
        _request(side=SimulatedTradeSide.SELL, fee_budget=None),
    )
    hold = result.reservation

    partially_filled = hold.apply_fill(
        filled_quantity=Decimal("3"),
        cash_consumed=Decimal("0.00"),
    )
    assert partially_filled.status is OrderReservationStatus.ACTIVE
    assert partially_filled.shares_consumed == Decimal("3.000000")
    assert partially_filled.remaining_shares == Decimal("7.000000")

    cancelled = partially_filled.release_remaining()
    assert cancelled.status is OrderReservationStatus.CANCELLED
    assert cancelled.shares_released == Decimal("7.000000")
    assert cancelled.shares_consumed + cancelled.shares_released == hold.shares_reserved
    assert cancelled.remaining_shares == Decimal("0.000000")
    assert cancelled.release_remaining() == cancelled
    with pytest.raises(OrderReservationError) as error:
        cancelled.apply_fill(
            filled_quantity=Decimal("1"),
            cash_consumed=Decimal("0.00"),
        )
    assert error.value.code == "ORDER_RESERVATION_TERMINAL"


def test_full_buy_fill_releases_unused_fee_budget_once() -> None:
    result = _reserve(
        _book(book_cash=Decimal("500.00")),
        _request(fee_budget=Decimal("1.00")),
    )

    completed = result.reservation.apply_fill(
        filled_quantity=Decimal("10"),
        cash_consumed=Decimal("100.50"),
    )

    assert completed.status is OrderReservationStatus.COMPLETED
    assert completed.cash_consumed == Decimal("100.50")
    assert completed.cash_released == Decimal("0.50")
    assert completed.cash_consumed + completed.cash_released == completed.cash_reserved
    assert completed.remaining_cash == Decimal("0.00")
    assert completed.release_remaining() == completed


def test_existing_active_holds_cannot_exceed_a_known_book_snapshot() -> None:
    first = _reserve(
        _book(book_cash=Decimal("1000.00")),
        _request(fee_budget=Decimal("1.00")),
    )

    with pytest.raises(OrderReservationError) as error:
        replace(first.book, book_cash=Decimal("100.00"))

    assert error.value.code == "BOOK_CASH_OVERHELD"


def test_notional_and_hold_totals_ignore_the_callers_decimal_context() -> None:
    request = _request(
        quantity=Decimal("1.234567"),
        limit_price=Decimal("2.0000"),
        fee_budget=Decimal("0.50"),
    )
    book = _book(book_cash=Decimal("100.00"))

    with localcontext() as context:
        context.prec = 2
        result = _reserve(book, request)

    assert result.reservation.notional == Decimal("2.47")
    assert result.reservation.cash_reserved == Decimal("2.97")
    assert result.book.available_cash == Decimal("97.03")


def test_naive_reservation_time_is_rejected_and_offset_time_is_normalized_to_utc() -> None:
    result = _reserve(_book(), _request())
    assert result.reservation.reserved_at == AS_OF

    with pytest.raises(OrderReservationError) as error:
        reserve_order(
            _book(),
            _request(),
            _fee_policy(),
            reserved_at=datetime(2026, 10, 16, 2, 0),
        )
    assert error.value.code == "RESERVED_AT_INVALID"


@pytest.mark.parametrize("close_order", ["false", 1, None])
def test_fill_rejects_non_boolean_terminal_flags_without_releasing_resources(
    close_order: object,
) -> None:
    original = _reserve(_book(), _request()).reservation
    with pytest.raises(OrderReservationError) as error:
        original.apply_fill(
            filled_quantity=Decimal("1"), cash_consumed=Decimal("10.00"), close_order=close_order
        )
    assert error.value.code == "CLOSE_ORDER_FLAG_INVALID"
    assert original.status is OrderReservationStatus.ACTIVE
    assert original.cash_released == Decimal("0")
