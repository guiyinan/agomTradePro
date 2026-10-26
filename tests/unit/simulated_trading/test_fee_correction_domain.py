"""Pure arithmetic contracts for G4 simulated-trade fee corrections."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from apps.simulated_trading.domain.execution_settlement_primitives import SimulatedTradeSide
from apps.simulated_trading.domain.fee_correction import (
    CorrectableFeeComponents,
    FeeCorrectionCashEvent,
    FeeCorrectionContractError,
    FeeCorrectionDelta,
    FeeCorrectionReplayTrade,
    calculate_fee_correction_delta,
    calculate_ledger_percentage,
    replay_average_cost_history,
    require_exact_signed_ledger_money,
    subtract_ledger_money,
    sum_ledger_money,
    sum_signed_ledger_money,
)

_BASE_TIME = datetime(2026, 10, 25, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "previous,revised,expected_cash",
    [
        ("0.00", "1001.11", "-1001.11"),
        ("1001.11", "0.00", "1001.11"),
        ("0.00", "12345.67", "-12345.67"),
        ("12345.67", "0.00", "12345.67"),
    ],
)
def test_cash_delta_preserves_every_cent_under_low_decimal_precision(
    previous: str, revised: str, expected_cash: str
) -> None:
    """Unary cash sign changes must retain cents under the caller's context."""
    old_fees = _fees(commission=previous)
    new_fees = _fees(commission=revised)
    with localcontext() as context:
        context.prec = 2
        result = calculate_fee_correction_delta(old_fees, new_fees)
    assert result.cash_delta == Decimal(expected_cash)


@pytest.mark.parametrize("component,cash", [("1001.11", "-1000.00"), ("-1001.11", "1000.00")])
def test_rounded_cash_inverse_cannot_pass_delta_reconciliation(component: str, cash: str) -> None:
    """An externally constructed delta cannot hide a cash error with low precision."""
    with localcontext() as context:
        context.prec = 2
        with pytest.raises(FeeCorrectionContractError, match="reconcile"):
            FeeCorrectionDelta(
                commission=Decimal(component),
                transfer_fee=Decimal("0.00"),
                stamp_duty=Decimal("0.00"),
                total_fee_delta=Decimal(component),
                cash_delta=Decimal(cash),
            )


def test_valid_signed_amount_near_ledger_limit_ignores_callers_precision() -> None:
    """An exact valid boundary amount must not round up during the range check."""
    amount = Decimal("9999999999999.99")
    with localcontext() as context:
        context.prec = 2
        result = FeeCorrectionDelta(
            commission=amount,
            transfer_fee=Decimal("0.00"),
            stamp_duty=Decimal("0.00"),
            total_fee_delta=amount,
            cash_delta=amount.copy_negate(),
        )
    assert result.total_fee_delta == amount


def test_unchanged_fee_keeps_canonical_unsigned_zero_cash_delta() -> None:
    """Exact sign operations must retain the prior canonical zero representation."""
    result = calculate_fee_correction_delta(_fees(), _fees())
    assert str(result.cash_delta) == "0.00"


def _fees(
    commission: str = "0.00",
    transfer_fee: str = "0.00",
    stamp_duty: str = "0.00",
) -> CorrectableFeeComponents:
    """Build exact cent amounts for one synthetic correction fixture."""

    return CorrectableFeeComponents(
        commission=Decimal(commission),
        transfer_fee=Decimal(transfer_fee),
        stamp_duty=Decimal(stamp_duty),
    )


def _trade(
    trade_id: int,
    side: SimulatedTradeSide,
    quantity: str,
    amount: str,
    fees: CorrectableFeeComponents,
    *,
    execution_time: datetime = _BASE_TIME,
    slippage: str = "0.00",
    account_id: int = 7,
    asset_code: str = "600000.SH",
    fee_amounts_known: bool | None = True,
    cost_basis_known: bool | None = True,
) -> FeeCorrectionReplayTrade:
    """Build one exact replay row with all provenance eligibility explicit."""

    return FeeCorrectionReplayTrade(
        trade_id=trade_id,
        account_id=account_id,
        asset_code=asset_code,
        execution_time=execution_time,
        side=side,
        quantity=Decimal(quantity),
        amount=Decimal(amount),
        fee_components=fees,
        original_slippage=Decimal(slippage),
        fee_amounts_known=fee_amounts_known,
        cost_basis_known=cost_basis_known,
    )


def test_fee_delta_seven_to_nine_debits_two() -> None:
    delta = calculate_fee_correction_delta(_fees("7.00"), _fees("9.00"))

    assert delta.commission == Decimal("2.00")
    assert delta.transfer_fee == Decimal("0.00")
    assert delta.stamp_duty == Decimal("0.00")
    assert delta.total_fee_delta == Decimal("2.00")
    assert delta.cash_delta == Decimal("-2.00")


def test_fee_delta_nine_to_seven_refunds_two() -> None:
    delta = calculate_fee_correction_delta(_fees("9.00"), _fees("7.00"))

    assert delta.total_fee_delta == Decimal("-2.00")
    assert delta.cash_delta == Decimal("2.00")


def test_fee_delta_reconciles_components_and_accepts_explicit_zero() -> None:
    delta = calculate_fee_correction_delta(
        _fees("1.00", "2.00", "3.00"),
        _fees("3.00", "1.00", "4.00"),
    )

    assert delta.commission == Decimal("2.00")
    assert delta.transfer_fee == Decimal("-1.00")
    assert delta.stamp_duty == Decimal("1.00")
    assert delta.total_fee_delta == Decimal("2.00")
    assert delta.cash_delta == Decimal("-2.00")
    assert calculate_fee_correction_delta(_fees(), _fees()).cash_delta == Decimal("0.00")


def test_fee_delta_is_independent_of_callers_decimal_precision() -> None:
    with localcontext() as context:
        context.prec = 2
        delta = calculate_fee_correction_delta(
            _fees("7.00", "0.10"),
            _fees("9.00", "0.30"),
        )

    assert delta.total_fee_delta == Decimal("2.20")
    assert delta.cash_delta == Decimal("-2.20")


def test_buy_fee_correction_replays_through_partial_sell_and_remaining_basis() -> None:
    original = replay_average_cost_history(
        (
            _trade(
                1,
                SimulatedTradeSide.BUY,
                "100.000000",
                "1000.00",
                _fees("7.00"),
                slippage="4.00",
            ),
            _trade(
                2,
                SimulatedTradeSide.SELL,
                "50.000000",
                "600.00",
                _fees("1.00"),
                execution_time=datetime(2026, 10, 26, 9, 30, tzinfo=UTC),
            ),
        )
    )
    corrected = replay_average_cost_history(
        (
            _trade(
                1,
                SimulatedTradeSide.BUY,
                "100.000000",
                "1000.00",
                _fees("9.00"),
                slippage="4.00",
            ),
            _trade(
                2,
                SimulatedTradeSide.SELL,
                "50.000000",
                "600.00",
                _fees("1.00"),
                execution_time=datetime(2026, 10, 26, 9, 30, tzinfo=UTC),
            ),
        )
    )

    assert original.steps[1].allocated_sale_cost == Decimal("505.50")
    assert corrected.steps[1].allocated_sale_cost == Decimal("506.50")
    assert original.steps[1].realized_pnl == Decimal("93.50")
    assert corrected.steps[1].realized_pnl == Decimal("92.50")
    assert original.ending_quantity == corrected.ending_quantity == Decimal("50.000000")
    assert original.ending_total_cost == Decimal("505.50")
    assert corrected.ending_total_cost == Decimal("506.50")
    assert corrected.ending_average_cost == Decimal("10.1300")


def test_replay_is_independent_of_callers_decimal_precision_and_keeps_slippage() -> None:
    trade = _trade(
        1,
        SimulatedTradeSide.BUY,
        "3.000000",
        "9.00",
        _fees("1.00"),
        slippage="0.50",
    )
    with localcontext() as context:
        context.prec = 2
        result = replay_average_cost_history((trade,))

    assert result.ending_total_cost == Decimal("10.50")
    assert result.ending_average_cost == Decimal("3.5000")
    assert trade.original_slippage == Decimal("0.50")


def test_sell_fee_correction_changes_realized_pnl_but_not_position_basis() -> None:
    def replay(sell_fee: str):
        return replay_average_cost_history(
            (
                _trade(
                    1,
                    SimulatedTradeSide.BUY,
                    "100.000000",
                    "1000.00",
                    _fees(),
                ),
                _trade(
                    2,
                    SimulatedTradeSide.SELL,
                    "50.000000",
                    "600.00",
                    _fees(sell_fee),
                    execution_time=datetime(2026, 10, 26, 9, 30, tzinfo=UTC),
                ),
            )
        )

    original = replay("7.00")
    corrected = replay("9.00")

    assert original.steps[1].realized_pnl == Decimal("93.00")
    assert corrected.steps[1].realized_pnl == Decimal("91.00")
    assert original.ending_total_cost == corrected.ending_total_cost == Decimal("500.00")


def test_final_sale_consumes_the_exact_cent_residual() -> None:
    result = replay_average_cost_history(
        (
            _trade(1, SimulatedTradeSide.BUY, "3.000000", "9.00", _fees("1.00")),
            _trade(
                2,
                SimulatedTradeSide.SELL,
                "1.000000",
                "5.00",
                _fees(),
                execution_time=datetime(2026, 10, 26, 9, 30, tzinfo=UTC),
            ),
            _trade(
                3,
                SimulatedTradeSide.SELL,
                "2.000000",
                "10.00",
                _fees(),
                execution_time=datetime(2026, 10, 27, 9, 30, tzinfo=UTC),
            ),
        )
    )

    assert result.steps[1].allocated_sale_cost == Decimal("3.33")
    assert result.steps[1].total_cost_after == Decimal("6.67")
    assert result.steps[2].allocated_sale_cost == Decimal("6.67")
    assert result.ending_quantity == Decimal("0.000000")
    assert result.ending_total_cost == Decimal("0.00")
    assert result.ending_average_cost is None


def test_equal_execution_time_uses_trade_id_for_stable_order() -> None:
    later_buy = _trade(2, SimulatedTradeSide.BUY, "100.000000", "2000.00", _fees())
    earlier_buy = _trade(1, SimulatedTradeSide.BUY, "100.000000", "1000.00", _fees())

    result = replay_average_cost_history((later_buy, earlier_buy))

    assert [step.trade_id for step in result.steps] == [1, 2]
    assert result.ending_quantity == Decimal("200.000000")
    assert result.ending_total_cost == Decimal("3000.00")
    assert result.ending_average_cost == Decimal("15.0000")


@pytest.mark.parametrize(
    ("fee_amounts_known", "cost_basis_known"),
    [
        (None, True),
        (True, False),
    ],
)
def test_unknown_fee_or_basis_history_fails_closed(
    fee_amounts_known: bool | None,
    cost_basis_known: bool | None,
) -> None:
    with pytest.raises(FeeCorrectionContractError):
        trade = _trade(
            1,
            SimulatedTradeSide.BUY,
            "10.000000",
            "100.00",
            _fees(),
            fee_amounts_known=fee_amounts_known,
            cost_basis_known=cost_basis_known,
        )
        replay_average_cost_history((trade,))


def test_sell_without_a_complete_prior_buy_history_fails_closed() -> None:
    sell = _trade(2, SimulatedTradeSide.SELL, "1.000000", "12.00", _fees())

    with pytest.raises(FeeCorrectionContractError, match="sell quantity exceeds"):
        replay_average_cost_history((sell,))


def test_replay_rejects_duplicate_trade_identity_and_mixed_asset_scope() -> None:
    buy = _trade(1, SimulatedTradeSide.BUY, "1.000000", "10.00", _fees())
    other_asset = _trade(
        2,
        SimulatedTradeSide.BUY,
        "1.000000",
        "10.00",
        _fees(),
        asset_code="000001.SZ",
    )

    with pytest.raises(FeeCorrectionContractError, match="duplicate trade IDs"):
        replay_average_cost_history((buy, buy))
    with pytest.raises(FeeCorrectionContractError, match="crosses account or asset"):
        replay_average_cost_history((buy, other_asset))


def test_replay_rejects_naive_execution_time() -> None:
    with pytest.raises(FeeCorrectionContractError, match="timezone-aware"):
        _trade(
            1,
            SimulatedTradeSide.BUY,
            "1.000000",
            "10.00",
            _fees(),
            execution_time=datetime(2026, 10, 25, 9, 30),
        )


@pytest.mark.parametrize(
    "commission",
    [
        Decimal("-0.01"),
        Decimal("0.001"),
        Decimal("NaN"),
    ],
)
def test_invalid_or_unrepresentable_fee_components_fail_closed(
    commission: Decimal,
) -> None:
    with pytest.raises(FeeCorrectionContractError):
        CorrectableFeeComponents(commission, Decimal("0.00"), Decimal("0.00"))


def test_fee_component_total_cannot_exceed_ledger_money_range() -> None:
    with pytest.raises(ValueError, match="correctable_fee_total"):
        CorrectableFeeComponents(
            Decimal("9999999999999.99"),
            Decimal("9999999999999.99"),
            Decimal("9999999999999.99"),
        )


def test_fee_correction_delta_rejects_untyped_inputs_and_inconsistent_totals() -> None:
    with pytest.raises(FeeCorrectionContractError, match="exact typed"):
        calculate_fee_correction_delta(_fees(), object())  # type: ignore[arg-type]

    with pytest.raises(FeeCorrectionContractError, match="finite Decimal"):
        FeeCorrectionDelta(
            commission=Decimal("0.00"),
            transfer_fee=0,  # type: ignore[arg-type]
            stamp_duty=Decimal("0.00"),
            total_fee_delta=Decimal("0.00"),
            cash_delta=Decimal("0.00"),
        )

    with pytest.raises(FeeCorrectionContractError, match="cent-denominated"):
        FeeCorrectionDelta(
            commission=Decimal("0.001"),
            transfer_fee=Decimal("0.00"),
            stamp_duty=Decimal("0.00"),
            total_fee_delta=Decimal("0.001"),
            cash_delta=Decimal("-0.001"),
        )

    with pytest.raises(FeeCorrectionContractError, match="do not reconcile"):
        FeeCorrectionDelta(
            commission=Decimal("1.00"),
            transfer_fee=Decimal("0.00"),
            stamp_duty=Decimal("0.00"),
            total_fee_delta=Decimal("1.00"),
            cash_delta=Decimal("1.00"),
        )


@pytest.mark.parametrize(
    "component_delta",
    [Decimal("1E+1000"), Decimal("10000000000000.00")],
)
def test_fee_correction_delta_rejects_unrepresentable_signed_values(
    component_delta: Decimal,
) -> None:
    with pytest.raises(FeeCorrectionContractError):
        FeeCorrectionDelta(
            commission=component_delta,
            transfer_fee=Decimal("0.00"),
            stamp_duty=Decimal("0.00"),
            total_fee_delta=component_delta,
            cash_delta=-component_delta,
        )


def test_replay_rejects_nonsequence_empty_and_untyped_histories() -> None:
    with pytest.raises(FeeCorrectionContractError, match="typed sequence"):
        replay_average_cost_history("not a trade sequence")  # type: ignore[arg-type]
    with pytest.raises(FeeCorrectionContractError, match="cannot be empty"):
        replay_average_cost_history(())
    with pytest.raises(FeeCorrectionContractError, match="untyped row"):
        replay_average_cost_history((object(),))  # type: ignore[arg-type]


def test_replay_rejects_partial_sale_that_cannot_preserve_cent_basis() -> None:
    buy = _trade(1, SimulatedTradeSide.BUY, "2.000000", "0.01", _fees())
    sell = _trade(
        2,
        SimulatedTradeSide.SELL,
        "1.000000",
        "0.02",
        _fees(),
        execution_time=datetime(2026, 10, 26, 9, 30, tzinfo=UTC),
    )

    with pytest.raises(FeeCorrectionContractError, match="cannot preserve"):
        replay_average_cost_history((buy, sell))


def test_replay_rejects_quantity_overflow_and_unrepresentable_average_cost() -> None:
    large_buy = _trade(
        1,
        SimulatedTradeSide.BUY,
        "99999999999999.000000",
        "9999999999999.99",
        _fees(),
    )
    extra_buy = _trade(2, SimulatedTradeSide.BUY, "1.000000", "0.01", _fees())
    with pytest.raises(ValueError, match="position.quantity_after_buy"):
        replay_average_cost_history((large_buy, extra_buy))

    tiny_position = _trade(3, SimulatedTradeSide.BUY, "0.000001", "1.00", _fees())
    with pytest.raises(ValueError, match="position.average_cost"):
        replay_average_cost_history((tiny_position,))


@pytest.mark.parametrize("trade_id", [True, 0, -1])
def test_replay_trade_rejects_invalid_trade_identity(trade_id: int) -> None:
    with pytest.raises(FeeCorrectionContractError, match="trade_id"):
        _trade(trade_id, SimulatedTradeSide.BUY, "1.000000", "10.00", _fees())


@pytest.mark.parametrize("account_id", [False, 0, -1])
def test_replay_trade_rejects_invalid_account_identity(account_id: int) -> None:
    with pytest.raises(FeeCorrectionContractError, match="account_id"):
        _trade(
            1,
            SimulatedTradeSide.BUY,
            "1.000000",
            "10.00",
            _fees(),
            account_id=account_id,
        )


@pytest.mark.parametrize("asset_code", ["", " 600000.SH", "600000. SH"])
def test_replay_trade_rejects_noncanonical_asset_identity(asset_code: str) -> None:
    with pytest.raises(FeeCorrectionContractError, match="asset_code"):
        _trade(
            1,
            SimulatedTradeSide.BUY,
            "1.000000",
            "10.00",
            _fees(),
            asset_code=asset_code,
        )


def test_replay_trade_rejects_unrecognized_side_and_invalid_slippage() -> None:
    from typing import cast

    with pytest.raises(FeeCorrectionContractError, match="trade side"):
        _trade(
            1,
            cast(SimulatedTradeSide, "buy"),
            "1.000000",
            "10.00",
            _fees(),
        )
    with pytest.raises(FeeCorrectionContractError, match="invalid exact ledger amount"):
        _trade(
            1,
            SimulatedTradeSide.BUY,
            "1.000000",
            "10.00",
            _fees(),
            slippage="-0.01",
        )


@pytest.mark.parametrize("cash", [Decimal("-1001.11"), Decimal("1001.11"), Decimal("0.00")])
def test_cash_event_retains_exact_debit_refund_and_posting_identity(cash: Decimal) -> None:
    """Cash-curve inputs retain independently posted exact correction amounts."""
    with localcontext() as context:
        context.prec = 2
        event = FeeCorrectionCashEvent(1, _BASE_TIME.date(), _BASE_TIME, cash)
    assert event.cash_delta == cash
    assert event.posted_at == _BASE_TIME
    assert event.posting_date == _BASE_TIME.date()


@pytest.mark.parametrize(
    "cash", [None, True, 1, "1.00", 1.0, Decimal("NaN"), Decimal("Infinity"), Decimal("0.001")]
)
def test_cash_event_rejects_unknown_or_inexact_amount_with_domain_error(cash: object) -> None:
    """Malformed external values must be a domain rejection, not AttributeError."""
    with pytest.raises(FeeCorrectionContractError):
        FeeCorrectionCashEvent(1, _BASE_TIME.date(), _BASE_TIME, cash)


@pytest.mark.parametrize("event_id", [None, True, 0, -1])
def test_cash_event_requires_exact_positive_identity(event_id: object) -> None:
    """A boolean or missing ID cannot identify an accounting event."""
    with pytest.raises(FeeCorrectionContractError):
        FeeCorrectionCashEvent(event_id, _BASE_TIME.date(), _BASE_TIME, Decimal("0.00"))


def test_cash_event_does_not_accept_datetime_as_posting_date() -> None:
    """Date and datetime have distinct persistence and financial-cutoff meanings."""
    with pytest.raises(FeeCorrectionContractError):
        FeeCorrectionCashEvent(1, _BASE_TIME, _BASE_TIME, Decimal("0.00"))


def test_cash_event_requires_aware_posting_clock() -> None:
    """Unknown timezone cannot become a factual correction posting clock."""
    with pytest.raises(FeeCorrectionContractError):
        FeeCorrectionCashEvent(
            1, _BASE_TIME.date(), _BASE_TIME.replace(tzinfo=None), Decimal("0.00")
        )


def test_fee_delta_does_not_inherit_callers_exponent_or_traps() -> None:
    """Supported money remains exact even when unrelated caller math is restricted."""
    previous = _fees()
    revised = _fees("1001.11")
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        result = calculate_fee_correction_delta(previous, revised)
        assert context.prec == 2
        assert context.Emax == 2
        assert context.traps[Inexact]
        assert context.traps[Rounded]
    assert result.cash_delta == Decimal("-1001.11")


def test_cost_replay_uses_its_own_declared_rounding_context() -> None:
    """Average-cost division must not inherit a caller's Inexact trap."""
    buy = _trade(1, SimulatedTradeSide.BUY, "3", "1000.00", _fees("1.11"))
    sell = _trade(2, SimulatedTradeSide.SELL, "1", "500.00", _fees("1.00"))
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        result = replay_average_cost_history([buy, sell])
    assert result.ending_quantity == Decimal("2")
    assert result.ending_total_cost == Decimal("667.41")


def test_infrastructure_cash_helpers_ignore_hostile_decimal_context() -> None:
    """Cash history sums, differences, and validation share the Domain context."""
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        signed = sum_signed_ledger_money(
            (Decimal("12345.67"), Decimal("-100.01")),
            "cash_delta",
        )
        fees = sum_ledger_money(
            (Decimal("12345.67"), Decimal("100.01")),
            "fees",
        )
        difference = subtract_ledger_money(Decimal("12345.67"), Decimal("100.01"), "cash_delta")
        exact = require_exact_signed_ledger_money(Decimal("-12345.67"), "cash_delta")
        percentage = calculate_ledger_percentage(Decimal("1.00"), Decimal("3.00"))
        assert context.prec == 2
        assert context.Emax == 2
        assert context.Emin == -2
        assert context.traps[Inexact]
        assert context.traps[Rounded]

    assert signed == Decimal("12245.66")
    assert fees == Decimal("12445.68")
    assert difference == Decimal("12245.66")
    assert exact == Decimal("-12345.67")
    assert percentage > Decimal("33.33")


def test_exact_signed_money_rejects_subcent_amount_under_hostile_context() -> None:
    """An ambient low-precision context cannot round invalid stored cents into validity."""
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        with pytest.raises(FeeCorrectionContractError):
            require_exact_signed_ledger_money(Decimal("-1.001"), "cash_delta")
