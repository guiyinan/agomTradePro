"""Gold cases for unadjusted action returns and double-count prevention."""

from decimal import Decimal

import pytest

from apps.simulated_trading.domain.security_action_valuation import (
    SecurityActionReturnInput,
    reconcile_security_action_return,
)


def test_cash_entitlement_offsets_ex_dividend_price_drop_once() -> None:
    value = SecurityActionReturnInput(
        quantity_before=Decimal("10"),
        quantity_after=Decimal("10"),
        price_before=Decimal("10"),
        price_after=Decimal("9.8"),
        cash_entitlement=Decimal("2"),
        price_basis="unadjusted",
        share_delivery_confirmed=False,
    )

    assert reconcile_security_action_return(value) == Decimal("0")


def test_confirmed_share_delivery_offsets_unadjusted_price_change() -> None:
    value = SecurityActionReturnInput(
        quantity_before=Decimal("10"),
        quantity_after=Decimal("14"),
        price_before=Decimal("14"),
        price_after=Decimal("10"),
        cash_entitlement=Decimal("0"),
        price_basis="unadjusted",
        share_delivery_confirmed=True,
    )

    assert reconcile_security_action_return(value) == Decimal("0")


def test_preadjusted_input_cannot_repeat_cash_or_share_action() -> None:
    with pytest.raises(ValueError, match="unadjusted"):
        SecurityActionReturnInput(
            quantity_before=Decimal("10"),
            quantity_after=Decimal("10"),
            price_before=Decimal("10"),
            price_after=Decimal("10"),
            cash_entitlement=Decimal("2"),
            price_basis="forward_adjusted",
            share_delivery_confirmed=False,
        )


def test_unconfirmed_odd_lot_share_delivery_cannot_be_valued() -> None:
    with pytest.raises(ValueError, match="confirmed share delivery"):
        SecurityActionReturnInput(
            quantity_before=Decimal("3"),
            quantity_after=Decimal("4"),
            price_before=Decimal("14"),
            price_after=Decimal("10"),
            cash_entitlement=Decimal("0"),
            price_basis="unadjusted",
            share_delivery_confirmed=False,
        )
