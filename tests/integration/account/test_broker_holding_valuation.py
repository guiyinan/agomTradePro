"""Holdings remain usable without treating costs or placeholders as market prices."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from apps.account.infrastructure import models as account_models
from apps.simulated_trading.infrastructure import models as ledger_models


@pytest.mark.django_db
def test_legacy_holding_without_quote_is_adopted_with_explicit_unknown_valuation() -> None:
    """The actual position-read caller preserves quantity and cost without inventing price."""
    owner = User.objects.create_user(username="legacy-unvalued-owner")
    portfolio = account_models.PortfolioModel._default_manager.create(
        user=owner, name="Unvalued source holding"
    )
    legacy = account_models.PositionModel._default_manager.create(
        portfolio=portfolio,
        asset_code="600000.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=100,
        avg_cost=Decimal("10"),
        current_price=None,
    )
    client = APIClient()
    client.force_authenticate(owner)
    response = client.get(f"/api/account/portfolios/{portfolio.pk}/positions/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.data["count"] == 1
    row = response.data["data"][0]
    assert row["shares"] == 100
    assert Decimal(str(row["avg_cost"])) == Decimal("10")
    assert row["current_price"] is None
    assert row["market_value"] is None
    assert row["unrealized_pnl"] is None
    assert row["valuation_known"] is False
    assert row["valuation_status"] == "unknown"
    position_map = ledger_models.LedgerMigrationMapModel._default_manager.get(
        source_app="account", source_table="position", source_id=legacy.pk
    )
    position = ledger_models.PositionModel._default_manager.get(pk=position_map.target_id)
    assert position.quantity == Decimal("100")
    assert position.total_cost == Decimal("1000")
    assert position.valuation_known is False
    assert position.current_price == Decimal("0")
    assert not ledger_models.SimulatedTradeModel._default_manager.filter(
        account_id=position.account_id
    ).exists()
    canonical = client.get(f"/api/account/accounts/{position.account_id}/positions/")
    assert canonical.status_code == 200
    assert canonical["Content-Type"].startswith("application/json")
    assert canonical.data["positions"][0]["current_price"] is None
    assert canonical.data["total_market_value"] is None
    assert canonical.data["valuation_known"] is False


@pytest.mark.django_db
def test_observer_reads_unknown_valuation_without_zero_coercion() -> None:
    """A valid observer grant exposes real holdings and an incomplete value summary."""
    owner = User.objects.create_user(username="unvalued-observer-owner")
    observer = User.objects.create_user(username="unvalued-observer")
    portfolio = account_models.PortfolioModel._default_manager.create(user=owner, name="Observed")
    account_models.PositionModel._default_manager.create(
        portfolio=portfolio,
        asset_code="600000.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=100,
        avg_cost=Decimal("10"),
        current_price=None,
        market_value=Decimal("0"),
        unrealized_pnl=Decimal("0"),
    )
    grant = account_models.PortfolioObserverGrantModel._default_manager.create(
        owner_user_id=owner,
        observer_user_id=observer,
        expires_at=timezone.now() + timedelta(days=1),
    )
    client = APIClient()
    client.force_authenticate(observer)
    response = client.get(f"/api/account/observer-grants/{grant.pk}/positions/")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    data = response.data["data"]
    row = data["positions"][0]
    assert row["shares"] == 100
    assert row["current_price"] is None
    assert row["market_value"] is None
    assert row["unrealized_pnl"] is None
    assert row["valuation_known"] is False
    assert data["statistics"]["total_value"] is None
    assert data["statistics"]["total_cost"] == 1000
    assert data["statistics"]["total_pnl"] is None
    assert data["statistics"]["valuation_known"] is False
