"""Protected money helpers used by persisted fee correction history."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal, Inexact, Rounded, getcontext, localcontext
from typing import cast

import pytest

from apps.simulated_trading.domain.fee_correction import (
    FeeCorrectionContractError,
    calculate_ledger_percentage,
    require_exact_ledger_money,
    require_exact_ledger_price,
    require_exact_ledger_quantity,
    require_exact_signed_ledger_money,
    subtract_ledger_money,
    sum_ledger_money,
    sum_signed_ledger_money,
)


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (lambda: require_exact_ledger_money(Decimal("1001.11"), "money"), Decimal("1001.11")),
        (lambda: require_exact_ledger_price(Decimal("123.4567"), "price"), Decimal("123.4567")),
        (
            lambda: require_exact_ledger_quantity(Decimal("12345.670001"), "shares"),
            Decimal("12345.670001"),
        ),
        (
            lambda: require_exact_signed_ledger_money(Decimal("-1001.11"), "cash"),
            Decimal("-1001.11"),
        ),
        (
            lambda: sum_ledger_money((Decimal("1001.11"), Decimal("0.01")), "fees"),
            Decimal("1001.12"),
        ),
        (
            lambda: sum_signed_ledger_money((Decimal("1001.11"), Decimal("-123.45")), "cash"),
            Decimal("877.66"),
        ),
        (
            lambda: subtract_ledger_money(Decimal("1.11"), Decimal("1001.11"), "refund"),
            Decimal("-1000.00"),
        ),
        (lambda: calculate_ledger_percentage(Decimal("-12.50"), Decimal("50.00")), Decimal("-25")),
    ],
)
def test_caller_precision_exponents_and_traps_do_not_change_money(
    operation: Callable[[], Decimal], expected: Decimal
) -> None:
    """Use all helpers under a deliberately hostile ambient Decimal context."""
    with localcontext() as context:
        context.prec = 2
        context.Emax = 3
        context.Emin = -3
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        assert operation() == expected
        assert getcontext().prec == 2
        assert getcontext().Emax == 3
        assert getcontext().traps[Inexact]
        assert getcontext().traps[Rounded]


@pytest.mark.parametrize(
    "validator",
    [require_exact_ledger_money, require_exact_ledger_quantity, require_exact_ledger_price],
)
def test_nonnegative_validators_preserve_zero_and_explicit_zero_policy(
    validator: Callable[..., Decimal],
) -> None:
    """A caller must opt out of zero explicitly; booleans are not policy flags."""
    assert validator(Decimal("0"), "value") == Decimal("0")
    assert validator(Decimal("1"), "value", allow_zero=False) == Decimal("1")
    with pytest.raises(FeeCorrectionContractError):
        validator(Decimal("0"), "value", allow_zero=False)
    with pytest.raises(FeeCorrectionContractError):
        validator(Decimal("1"), "value", allow_zero=1)


@pytest.mark.parametrize(
    "validator",
    [require_exact_ledger_money, require_exact_ledger_quantity, require_exact_ledger_price],
)
@pytest.mark.parametrize(
    "bad", [None, True, 1, 1.0, "1.00", Decimal("NaN"), Decimal("Infinity"), Decimal("-0.01")]
)
def test_nonnegative_validators_reject_unknown_lossy_or_negative_values(
    validator: Callable[..., Decimal], bad: object
) -> None:
    """Known flags or implicit coercion cannot turn malformed amounts into money."""
    with pytest.raises(FeeCorrectionContractError):
        validator(cast(Decimal, bad), "value")


@pytest.mark.parametrize(
    ("validator", "bad"),
    [
        (require_exact_ledger_money, Decimal("0.001")),
        (require_exact_ledger_money, Decimal("10000000000000")),
        (require_exact_ledger_quantity, Decimal("0.0000001")),
        (require_exact_ledger_quantity, Decimal("100000000000000")),
        (require_exact_ledger_price, Decimal("0.00001")),
        (require_exact_ledger_price, Decimal("1000000")),
    ],
)
def test_nonnegative_validators_refuse_excess_precision_and_storage_overflow(
    validator: Callable[..., Decimal], bad: Decimal
) -> None:
    """Stored ledger values must already meet their physical quantum and cap."""
    with pytest.raises(FeeCorrectionContractError):
        validator(bad, "value")


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        1.0,
        "1.00",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("0.001"),
        Decimal("10000000000000"),
        Decimal("-10000000000000"),
    ],
)
def test_signed_money_rejects_non_decimal_non_cent_and_overflow(bad: object) -> None:
    """Signed cash accepts refunds while preserving exact storage bounds."""
    with pytest.raises(FeeCorrectionContractError):
        require_exact_signed_ledger_money(cast(Decimal, bad), "cash")


def test_signed_zero_and_large_cancellation_are_preserved() -> None:
    """A wide working sum must not lose cents or retain negative zero."""
    zero = require_exact_signed_ledger_money(Decimal("-0.00"), "cash")
    assert zero == Decimal("0.00") and not zero.is_signed()
    assert sum_signed_ledger_money(
        (Decimal("9000000000000.00"), Decimal("-9000000000000.00"), Decimal("1.01")), "cash"
    ) == Decimal("1.01")
    assert sum_ledger_money((), "fees") == Decimal("0.00")
    assert sum_signed_ledger_money((), "cash") == Decimal("0.00")


@pytest.mark.parametrize("summer", [sum_ledger_money, sum_signed_ledger_money])
@pytest.mark.parametrize(
    "bad", [None, "1.00", b"1.00", {Decimal("1.00")}, {"amount": Decimal("1.00")}]
)
def test_money_sums_require_an_explicit_sequence(
    summer: Callable[[Sequence[Decimal], str], Decimal], bad: object
) -> None:
    """Unordered or string containers cannot become an ordered money series."""
    with pytest.raises(FeeCorrectionContractError):
        summer(cast(Sequence[Decimal], bad), "cash")


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        1.0,
        "1.00",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("0.001"),
        Decimal("-0.01"),
    ],
)
def test_nonnegative_sum_rejects_invalid_members(bad: object) -> None:
    """Every fee component must be an exact known nonnegative amount."""
    with pytest.raises(FeeCorrectionContractError):
        sum_ledger_money((Decimal("1.00"), cast(Decimal, bad)), "fees")


def test_sum_and_subtraction_refuse_result_overflow() -> None:
    """Valid operands cannot produce an unrepresentable financial result."""
    with pytest.raises(FeeCorrectionContractError):
        sum_ledger_money((Decimal("9000000000000"), Decimal("9000000000000")), "fees")
    with pytest.raises(FeeCorrectionContractError):
        sum_signed_ledger_money((Decimal("9000000000000"), Decimal("9000000000000")), "cash")
    with pytest.raises(FeeCorrectionContractError):
        subtract_ledger_money(Decimal("9000000000000"), Decimal("-9000000000000"), "cash")
    with pytest.raises(FeeCorrectionContractError):
        subtract_ledger_money(Decimal("0.001"), Decimal("1.00"), "cash")


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [
        (None, Decimal("1")),
        (Decimal("1"), None),
        (1.0, Decimal("1")),
        (Decimal("NaN"), Decimal("1")),
        (Decimal("1"), Decimal("Infinity")),
        (Decimal("1"), Decimal("0")),
        (Decimal("1"), Decimal("-1")),
        (Decimal("1e999999"), Decimal("1e-999999")),
    ],
)
def test_percentage_requires_finite_decimals_and_positive_denominator(
    numerator: object, denominator: object
) -> None:
    """Percentages preserve losses and reject undefined or overflowing ratios."""
    with pytest.raises(FeeCorrectionContractError):
        calculate_ledger_percentage(cast(Decimal, numerator), cast(Decimal, denominator))
