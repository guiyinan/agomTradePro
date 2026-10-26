"""Infrastructure cash reconstruction shares the complete Domain Decimal context."""

from __future__ import annotations

from decimal import Decimal, Inexact, Rounded, localcontext
from types import SimpleNamespace

from apps.simulated_trading.infrastructure.fee_correction_history import (
    _cash_delta_for_trade,
    _exact_signed_money,
    _money_add,
    _money_sum,
)


def test_history_money_helpers_ignore_hostile_decimal_context() -> None:
    """Stored signed cents and additive fee totals remain exact under caller traps."""
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True

        exact = _exact_signed_money(Decimal("-12345.67"), "test.cash")
        added = _money_add(Decimal("12345.67"), Decimal("-100.01"), "test.cash")
        total = _money_sum((Decimal("12345.67"), Decimal("100.01")), "test.fees")

        assert context.prec == 2
        assert context.Emax == 2
        assert context.Emin == -2
        assert context.traps[Inexact]
        assert context.traps[Rounded]

    assert exact == Decimal("-12345.67")
    assert added == Decimal("12245.66")
    assert total == Decimal("12445.68")


def test_cash_reconstruction_uses_context_safe_signed_difference() -> None:
    """A SELL cash fact keeps its cents without ambient exponent privileges."""
    trade = SimpleNamespace(
        status="executed",
        action="sell",
        amount=Decimal("12345.67"),
        total_cost=Decimal("100.01"),
        commission=Decimal("50.00"),
        transfer_fee=Decimal("40.00"),
        stamp_duty=Decimal("5.00"),
        slippage=Decimal("5.01"),
        fee_amounts_known=True,
    )
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        cash_delta = _cash_delta_for_trade(trade)

    assert cash_delta == Decimal("12245.66")
