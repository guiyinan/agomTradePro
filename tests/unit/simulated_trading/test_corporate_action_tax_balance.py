"""Tax debt changes net assets and spending capacity without changing gross cash."""

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_balance import (
    CorporateActionTaxBalance,
    TaxBalanceBlockReason,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)


def _balance(**changes):
    values = {
        "currency": SimulatedDividendTaxCurrency.CNY,
        "currency_quantum": Decimal("0.01"),
        "book_cash": Decimal("100"),
        "marked_assets": Decimal("900"),
        "dividend_receivable": Decimal("0"),
        "tax_payable": Decimal("20"),
        "order_cash_reserved": Decimal("10"),
        "source_complete": True,
        "declared_blockers": (),
    }
    values.update(changes)
    return CorporateActionTaxBalance(**values)


def test_unpaid_tax_reduces_nav_and_spendable_cash_without_relabeling_book_cash():
    result = _balance()
    assert result.book_cash == Decimal("100")
    assert result.net_asset_value == Decimal("980")
    assert result.spendable_cash == Decimal("70")
    assert result.must_not_use_for_decision is False
    assert result.blocking_reasons == ()


def test_partial_and_final_collection_preserve_net_assets():
    original = _balance(order_cash_reserved=Decimal("0"))
    partial = replace(original, book_cash=Decimal("85"), tax_payable=Decimal("5"))
    complete = replace(partial, book_cash=Decimal("80"), tax_payable=Decimal("0"))
    assert original.net_asset_value == partial.net_asset_value == complete.net_asset_value
    assert original.spendable_cash == partial.spendable_cash == complete.spendable_cash


def test_refund_correction_increases_assets_only_by_the_corrected_tax_difference():
    original = _balance(book_cash=Decimal("85"), tax_payable=Decimal("5"))
    corrected = replace(original, book_cash=Decimal("90"), tax_payable=Decimal("0"))
    assert corrected.net_asset_value - original.net_asset_value == Decimal("10")


def test_receivable_payment_does_not_count_the_same_dividend_twice():
    entitled = _balance(dividend_receivable=Decimal("50"), tax_payable=Decimal("10"))
    paid = replace(entitled, book_cash=Decimal("150"), dividend_receivable=Decimal("0"))
    assert entitled.net_asset_value == paid.net_asset_value == Decimal("1040")
    assert paid.spendable_cash - entitled.spendable_cash == Decimal("50")


def test_cash_shortfall_keeps_negative_net_assets_and_zero_spendable_cash():
    result = _balance(
        book_cash=Decimal("5"),
        marked_assets=Decimal("0"),
        tax_payable=Decimal("20"),
        order_cash_reserved=Decimal("0"),
    )
    assert result.net_asset_value == Decimal("-15")
    assert result.spendable_cash == Decimal("0")


@pytest.mark.parametrize(
    "field,reason",
    [
        ("book_cash", TaxBalanceBlockReason.CASH_BALANCE_UNKNOWN),
        ("marked_assets", TaxBalanceBlockReason.POSITION_VALUATION_UNKNOWN),
        ("dividend_receivable", TaxBalanceBlockReason.DIVIDEND_RECEIVABLE_UNKNOWN),
        ("tax_payable", TaxBalanceBlockReason.TAX_PAYABLE_UNKNOWN),
        ("order_cash_reserved", TaxBalanceBlockReason.ORDER_CASH_RESERVATION_UNKNOWN),
    ],
)
def test_missing_inputs_remain_unknown_with_stable_blockers(field, reason):
    result = _balance(**{field: None})
    assert result.net_asset_value is None
    assert result.must_not_use_for_decision is True
    assert reason in result.blocking_reasons
    if field != "marked_assets" and field != "dividend_receivable":
        assert result.spendable_cash is None


def test_new_unapplied_assessment_blocks_both_projections():
    result = _balance(declared_blockers=(TaxBalanceBlockReason.TAX_ASSESSMENT_NOT_APPLIED,))
    assert result.net_asset_value is None and result.spendable_cash is None
    assert result.must_not_use_for_decision is True


def test_incomplete_evidence_cannot_publish_known_zero_debt():
    result = _balance(tax_payable=Decimal("0"), source_complete=False)
    assert TaxBalanceBlockReason.SOURCE_INCOMPLETE in result.blocking_reasons
    assert result.net_asset_value is None and result.spendable_cash is None


def test_projection_is_exact_under_a_low_ambient_decimal_context():
    with localcontext() as context:
        context.prec = 2
        result = _balance(
            book_cash=Decimal("1234567890123.45"),
            marked_assets=Decimal("0.01"),
            dividend_receivable=Decimal("0.02"),
            tax_payable=Decimal("0.03"),
            order_cash_reserved=Decimal("0.04"),
        )
        assert result.net_asset_value == Decimal("1234567890123.45")
        assert result.spendable_cash == Decimal("1234567890123.38")


@pytest.mark.parametrize(
    "changes",
    [
        {"book_cash": Decimal("NaN")},
        {"tax_payable": Decimal("-0.01")},
        {"marked_assets": Decimal("0.001")},
        {"order_cash_reserved": Decimal("101")},
        {"book_cash": 100.0},
        {"source_complete": 1},
        {"declared_blockers": ("unknown",)},
    ],
)
def test_invalid_or_unreconciled_money_is_rejected(changes):
    with pytest.raises(DeferredDividendTaxValidationError):
        _balance(**changes)
