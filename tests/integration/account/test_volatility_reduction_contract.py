"""Atomicity and idempotency contract for portfolio volatility reductions."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from apps.account.infrastructure.models import (
    PortfolioModel,
    PositionModel,
    TransactionModel,
)
from apps.account.infrastructure.position_repository import PositionRepository


def _position(portfolio: PortfolioModel, asset_code: str) -> PositionModel:
    return PositionModel.objects.create(
        portfolio=portfolio,
        asset_code=asset_code,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=100,
        avg_cost=Decimal("10"),
        current_price=Decimal("12"),
        market_value=Decimal("1200"),
        source="manual",
        is_closed=False,
    )


@pytest.mark.django_db
def test_reduction_batch_executes_once_for_all_positions() -> None:
    user = User.objects.create_user(username="volatility-owner")
    portfolio = PortfolioModel.objects.create(user=user, name="volatility")
    first = _position(portfolio, "600000.SH")
    second = _position(portfolio, "000001.SZ")
    repository = PositionRepository()
    instructions = [
        {
            "position_id": first.id,
            "asset_code": first.asset_code,
            "shares": 50.0,
            "price": Decimal("12"),
        },
        {
            "position_id": second.id,
            "asset_code": second.asset_code,
            "shares": 25.0,
            "price": Decimal("12"),
        },
    ]

    executed = repository.execute_volatility_reduction(
        portfolio_id=portfolio.id,
        user_id=user.id,
        idempotency_key="same-snapshot",
        reason="risk",
        instructions=instructions,
    )
    repeated = repository.execute_volatility_reduction(
        portfolio_id=portfolio.id,
        user_id=user.id,
        idempotency_key="same-snapshot",
        reason="risk",
        instructions=instructions,
    )

    first.refresh_from_db()
    second.refresh_from_db()
    assert executed["status"] == "executed"
    assert repeated == {"status": "already_executed", "reduced_positions": []}
    assert first.shares == 50
    assert second.shares == 75
    assert TransactionModel.objects.filter(action="sell").count() == 2


@pytest.mark.django_db
def test_invalid_later_instruction_rolls_back_whole_batch() -> None:
    user = User.objects.create_user(username="volatility-rollback")
    portfolio = PortfolioModel.objects.create(user=user, name="volatility")
    first = _position(portfolio, "600000.SH")
    second = _position(portfolio, "000001.SZ")
    repository = PositionRepository()

    with pytest.raises(ValueError, match="数量已失效"):
        repository.execute_volatility_reduction(
            portfolio_id=portfolio.id,
            user_id=user.id,
            idempotency_key="invalid-batch",
            reason="risk",
            instructions=[
                {
                    "position_id": first.id,
                    "asset_code": first.asset_code,
                    "shares": 50.0,
                    "price": Decimal("12"),
                },
                {
                    "position_id": second.id,
                    "asset_code": second.asset_code,
                    "shares": 200.0,
                    "price": Decimal("12"),
                },
            ],
        )

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.shares == 100
    assert second.shares == 100
    assert not TransactionModel.objects.filter(action="sell").exists()
