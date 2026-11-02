"""Exact threshold boundaries shared by observation and locked execution."""

from decimal import Decimal, localcontext
from typing import Any

import pytest

from apps.simulated_trading.domain.account_stop_loss import evaluate_account_stop_loss
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
)


@pytest.mark.parametrize(
    ("price", "triggered", "pnl_pct"),
    [("89", True, "-11"), ("90", False, "-10"), ("95", False, "-5"), ("120", False, "20")],
)
def test_threshold_uses_actual_total_cost_and_strict_loss_boundary(
    price: str, triggered: bool, pnl_pct: str
) -> None:
    result = evaluate_account_stop_loss(
        price=Decimal(price),
        quantity=Decimal("100"),
        total_cost=Decimal("10000"),
        threshold_pct=Decimal("10"),
    )
    assert result.triggered is triggered
    assert result.average_cost == Decimal("100")
    assert result.pnl_pct == Decimal(pnl_pct)


def test_threshold_does_not_depend_on_callers_decimal_precision() -> None:
    with localcontext() as context:
        context.prec = 3
        result = evaluate_account_stop_loss(
            price=Decimal("89.999999"),
            quantity=Decimal("100"),
            total_cost=Decimal("10000"),
            threshold_pct=Decimal("10"),
        )
    assert result.triggered is True
    assert result.pnl_pct == Decimal("-10.000001")


@pytest.mark.parametrize("field", ["price", "quantity", "total_cost", "threshold_pct"])
@pytest.mark.parametrize(
    "invalid", [None, True, "100", Decimal(0), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")]
)
def test_unknown_nonfinite_or_invalid_economic_input_cannot_become_a_trigger(
    field: str, invalid: Any
) -> None:
    values: dict[str, Any] = {
        "price": Decimal("80"),
        "quantity": Decimal("100"),
        "total_cost": Decimal("10000"),
        "threshold_pct": Decimal("10"),
    }
    values[field] = invalid
    with pytest.raises(SimulatedSettlementContractError):
        evaluate_account_stop_loss(**values)
