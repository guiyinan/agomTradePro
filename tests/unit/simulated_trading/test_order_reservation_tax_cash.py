"""Pure-domain checks for applying qualified tax cash holds to new orders."""

from __future__ import annotations

import inspect
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
    """Build an explicit fee policy with the requested commission floor."""

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
        policy_id="reservation-tax-cash-test",
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
    tax_cash_unavailable: Decimal | None = Decimal("0.00"),
) -> OrderReservationBook:
    """Build one source snapshot with a separately supplied tax cash amount."""

    return OrderReservationBook(
        account_id=9,
        security_id=security_id,
        book_cash=book_cash,
        withdrawable_cash=withdrawable_cash,
        sellable_shares=sellable_shares,
        reservations=reservations,
        tax_cash_unavailable=tax_cash_unavailable,
    )


def _request(
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    quantity: Decimal = Decimal("10"),
    limit_price: Decimal = Decimal("10.00"),
    fee_budget: Decimal | None = Decimal("0.50"),
    idempotency_key: str = "tax-cash-order",
) -> OrderReservationRequest:
    """Build one exact BUY or SELL request for the source snapshot."""

    return OrderReservationRequest(
        account_id=9,
        security_id="SH.600000",
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
    minimum_commission: Decimal = Decimal("0.50"),
) -> OrderReservationResult:
    """Reserve against an exact policy at the known UTC cutoff."""

    return reserve_order(
        book,
        request,
        _fee_policy(minimum_commission=minimum_commission),
        reserved_at=AS_OF,
    )


def test_tax_cash_amount_is_keyword_only_and_legacy_omission_means_no_tax_hold() -> None:
    """Existing positional book callers keep the former gross-cash behavior."""

    parameter = inspect.signature(OrderReservationBook).parameters["tax_cash_unavailable"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default == Decimal("0.00")

    book = OrderReservationBook(9, "SH.600000", Decimal("1000.00"), None, Decimal("100"), ())

    assert book.tax_cash_unavailable == Decimal("0.00")
    assert book.book_cash == Decimal("1000.00")
    assert book.available_cash == Decimal("1000.00")
    assert _reserve(book, _request()).reservation.cash_reserved == Decimal("100.50")


def test_known_tax_cash_is_subtracted_after_active_holds_without_changing_source_amounts() -> None:
    """The next order sees gross holds first and tax debt second, exactly."""

    first = _reserve(
        _book(
            book_cash=Decimal("150.00"),
            withdrawable_cash=Decimal("80.00"),
            tax_cash_unavailable=Decimal("20.01"),
        ),
        _request(idempotency_key="first", fee_budget=Decimal("1.00")),
    )

    assert first.book.book_cash == Decimal("150.00")
    assert first.book.withdrawable_cash == Decimal("80.00")
    assert first.book.active_held_cash == Decimal("101.00")
    assert first.book.tax_cash_unavailable == Decimal("20.01")
    with localcontext() as context:
        context.prec = 2
        available_cash = first.book.available_cash
    assert available_cash == Decimal("28.99")


def test_tax_debt_above_free_cash_blocks_new_orders_but_preserves_existing_holds() -> None:
    """A changed tax hold cannot rewrite or invalidate an accepted order."""

    first_request = _request(idempotency_key="existing", fee_budget=Decimal("1.00"))
    first = _reserve(_book(book_cash=Decimal("150.00")), first_request)
    taxed = replace(first.book, tax_cash_unavailable=Decimal("60.00"))

    assert taxed.book_cash == Decimal("150.00")
    assert taxed.active_held_cash == Decimal("101.00")
    assert taxed.reservations == (first.reservation,)
    assert taxed.available_cash == Decimal("0.00")
    assert _reserve(taxed, first_request).replayed is True
    assert (
        first.reservation.apply_fill(
            filled_quantity=Decimal("10"), cash_consumed=Decimal("100.50")
        ).status
        is OrderReservationStatus.COMPLETED
    )

    with pytest.raises(OrderReservationError) as error:
        _reserve(
            taxed,
            _request(quantity=Decimal("1"), idempotency_key="new", fee_budget=Decimal("0.50")),
        )
    assert error.value.code == "INSUFFICIENT_AVAILABLE_CASH"


def test_known_tax_debt_blocks_a_new_sell_fee_deficit() -> None:
    """A SELL may hold shares while its uncovered fee requires known cash."""

    book = _book(
        book_cash=Decimal("149.99"),
        sellable_shares=Decimal("20"),
        tax_cash_unavailable=Decimal("100.00"),
    )
    assert book.available_cash == Decimal("49.99")

    with pytest.raises(OrderReservationError) as error:
        _reserve(
            book,
            _request(side=SimulatedTradeSide.SELL, fee_budget=None),
            minimum_commission=Decimal("150.00"),
        )
    assert error.value.code == "INSUFFICIENT_AVAILABLE_CASH"
    assert book.reservations == ()


def test_unknown_tax_cash_blocks_buy_and_sell_fee_debits_but_not_zero_debit_sell() -> None:
    """Unknown tax debt stays unknown and only blocks orders needing cash."""

    book = _book(book_cash=Decimal("1000.00"), tax_cash_unavailable=None)
    assert book.available_cash is None

    with pytest.raises(OrderReservationError) as buy_error:
        _reserve(book, _request())
    assert buy_error.value.code == "BOOK_CASH_UNKNOWN"

    sell_request = _request(side=SimulatedTradeSide.SELL, fee_budget=None)
    with pytest.raises(OrderReservationError) as sell_error:
        _reserve(book, sell_request, minimum_commission=Decimal("150.00"))
    assert sell_error.value.code == "BOOK_CASH_UNKNOWN_FOR_SELL_FEE_DEFICIT"

    no_debit_sell = _reserve(book, sell_request)
    assert no_debit_sell.reservation.cash_reserved == Decimal("0.00")
    assert no_debit_sell.book.tax_cash_unavailable is None
    assert no_debit_sell.book.available_cash is None


@pytest.mark.parametrize(
    "invalid_tax_cash",
    (
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("1.001"),
        Decimal("10000000000000.00"),
    ),
)
def test_tax_cash_rejects_values_outside_ledger_money_storage(invalid_tax_cash: Decimal) -> None:
    """Tax cash uses the same finite, cent-exact bounds as ledger money."""

    with pytest.raises(SimulatedTradeIntentValidationError):
        _book(tax_cash_unavailable=invalid_tax_cash)
