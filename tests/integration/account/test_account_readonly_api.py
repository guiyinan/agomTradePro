"""Side-effect contract for governed Account read endpoints."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.account.infrastructure.models import PortfolioModel, PositionModel
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    SimulatedAccountModel,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel as SimulatedPositionModel,
)


@pytest.mark.django_db
def test_position_read_only_endpoint_does_not_synchronize_ledgers():
    user = User.objects.create_user(username="account_read_only", password="x")
    portfolio = PortfolioModel.objects.create(
        user=user,
        name="Read-only portfolio",
        is_active=True,
    )
    position = PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="510300.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=100,
        avg_cost=Decimal("3.8000"),
        current_price=Decimal("3.9000"),
        market_value=Decimal("390.00"),
        unrealized_pnl=Decimal("10.00"),
        unrealized_pnl_pct=2.63,
        source="manual",
        is_closed=False,
    )
    before = {
        "accounts": SimulatedAccountModel._default_manager.count(),
        "positions": SimulatedPositionModel._default_manager.count(),
        "mappings": LedgerMigrationMapModel._default_manager.count(),
    }

    client = APIClient()
    client.force_authenticate(user)
    response = client.get(
        "/api/account/positions/read-only/",
        {"portfolio_id": portfolio.id, "include_closed": "false"},
    )

    assert response.status_code == 200
    payload = response.json()
    rows = payload.get("results", payload)
    assert len(rows) == 1
    assert rows[0]["id"] == position.id
    assert rows[0]["asset_code"] == "510300.SH"
    assert SimulatedAccountModel._default_manager.count() == before["accounts"]
    assert SimulatedPositionModel._default_manager.count() == before["positions"]
    assert LedgerMigrationMapModel._default_manager.count() == before["mappings"]
