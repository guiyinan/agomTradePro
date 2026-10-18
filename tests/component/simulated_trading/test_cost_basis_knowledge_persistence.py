"""Regression tests for preserving cost-basis knowledge during ORM saves."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedAccountModel
from apps.simulated_trading.infrastructure.position_repository import (
    DjangoPositionRepository,
    PositionMapper,
)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stored_known", "incoming_known", "change_field", "expected_known"),
    (
        pytest.param(True, None, None, True, id="omitted-knowledge-noop-keeps-known"),
        pytest.param(True, None, "cost", None, id="changed-cost-without-proof-downgrades"),
        pytest.param(True, None, "quantity", None, id="changed-quantity-without-proof-downgrades"),
        pytest.param(True, None, "average", None, id="changed-average-without-proof-downgrades"),
        pytest.param(None, True, "cost", None, id="legacy-unknown-cannot-be-upgraded"),
        pytest.param(False, True, "cost", False, id="partial-knowledge-remains-sticky"),
    ),
)
def test_generic_position_save_merges_knowledge_against_economic_changes(
    stored_known: bool | None,
    incoming_known: bool | None,
    change_field: str | None,
    expected_known: bool | None,
) -> None:
    """A changed numeric basis cannot keep or gain a completeness claim by omission."""

    suffix = uuid4().hex[:10]
    account = SimulatedAccountModel.objects.create(
        account_name=f"cost-knowledge-{suffix}",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
    )
    stored_position = PositionModel.objects.create(
        account=account,
        asset_code=f"CK{suffix}",
        asset_name="Cost knowledge save fixture",
        asset_type="equity",
        quantity=Decimal("100.000000"),
        available_quantity=Decimal("100.000000"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("1000.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 16),
        cost_basis_known=stored_known,
    )

    incoming = replace(
        PositionMapper.to_entity(stored_position),
        cost_basis_known=incoming_known,
    )
    if change_field == "cost":
        incoming = replace(
            incoming,
            avg_cost=12.3456,
            total_cost=1234.56,
        )
    elif change_field == "quantity":
        incoming = replace(incoming, quantity=150.0)
    elif change_field == "average":
        incoming = replace(incoming, avg_cost=12.3456)

    DjangoPositionRepository().save(incoming)

    stored_position.refresh_from_db()
    assert stored_position.cost_basis_known is expected_known
    assert stored_position.avg_cost == (
        Decimal("12.3456") if change_field in {"cost", "average"} else Decimal("10.0000")
    )
    assert stored_position.total_cost == (
        Decimal("1234.56") if change_field == "cost" else Decimal("1000.00")
    )
    assert stored_position.quantity == (
        Decimal("150.000000") if change_field == "quantity" else Decimal("100.000000")
    )
