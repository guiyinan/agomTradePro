"""Account summary and recorded-facts APIs preserve unified valuation knowledge."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from apps.account.infrastructure.models import PortfolioModel, PositionModel
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    SimulatedAccountModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel as UnifiedPositionModel,
)


@pytest.mark.django_db
def test_unknown_unified_valuation_nulls_account_estimates_but_keeps_cost_and_count() -> None:
    """A false unified flag overrides stale legacy price and zero ledger placeholders."""

    owner = User.objects.create_user(username="portfolio-unknown-valuation")
    portfolio = PortfolioModel._default_manager.create(
        user=owner,
        name="未知估值组合",
        is_active=True,
    )
    mapped_legacy_position = PositionModel._default_manager.create(
        portfolio=portfolio,
        asset_code="600000.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=100,
        avg_cost=Decimal("10"),
        current_price=Decimal("15"),
        market_value=Decimal("1500"),
        unrealized_pnl=Decimal("500"),
        unrealized_pnl_pct=50.0,
    )
    PositionModel._default_manager.create(
        portfolio=portfolio,
        asset_code="000002.SZ",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=50,
        avg_cost=Decimal("20"),
        current_price=Decimal("30"),
        market_value=Decimal("1500"),
        unrealized_pnl=Decimal("500"),
        unrealized_pnl_pct=50.0,
    )
    account = SimulatedAccountModel._default_manager.create(
        user=owner,
        account_name="未知估值实盘",
        account_type="real",
        initial_capital=Decimal("0"),
        current_cash=Decimal("0"),
        current_market_value=Decimal("0"),
        total_value=Decimal("0"),
        auto_trading_enabled=False,
    )
    unified_position = UnifiedPositionModel._default_manager.create(
        account=account,
        asset_code=mapped_legacy_position.asset_code,
        asset_name=mapped_legacy_position.asset_code,
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("0"),
        available_quantity_known=False,
        avg_cost=Decimal("10"),
        total_cost=Decimal("1000"),
        current_price=Decimal("0"),
        market_value=Decimal("0"),
        valuation_known=False,
        first_buy_date=timezone.now().date(),
        first_buy_date_known=False,
    )
    LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.pk,
        target_table="simulated_account",
        target_id=account.pk,
    )
    LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="position",
        source_id=mapped_legacy_position.pk,
        target_table="simulated_position",
        target_id=unified_position.pk,
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    statistics_response = client.get(f"/api/account/portfolios/{portfolio.pk}/statistics/")
    recorded_facts_response = client.get(f"/api/account/portfolios/{portfolio.pk}/recorded-facts/")

    assert statistics_response.status_code == 200
    statistics = statistics_response.data
    assert statistics["total_value"] is None
    assert Decimal(str(statistics["total_cost"])) == Decimal("2000")
    assert statistics["total_pnl"] is None
    assert statistics["total_pnl_pct"] is None
    assert statistics["position_count"] == 2
    assert statistics["asset_class_breakdown"] is None
    assert statistics["region_breakdown"] is None
    assert statistics["valuation_known"] is False
    assert statistics["valuation_status"] == "unknown"

    assert recorded_facts_response.status_code == 200
    recorded = recorded_facts_response.data
    assert recorded["positions"]["count"] == 2
    positions_by_code = {item["asset_code"]: item for item in recorded["positions"]["items"]}
    for asset_code in ("600000.SH", "000002.SZ"):
        item = positions_by_code[asset_code]
        assert item["shares"] > 0
        assert item["current_price"] is None
        assert item["market_value"] is None
        assert item["unrealized_pnl"] is None
        assert item["unrealized_pnl_pct"] is None
        assert item["valuation_known"] is False
        assert item["valuation_status"] == "unknown"
    assert Decimal(positions_by_code["600000.SH"]["avg_cost"]) == Decimal("10")
    recorded_statistics = recorded["statistics"]
    assert recorded_statistics["total_value"] is None
    assert Decimal(recorded_statistics["total_cost"]) == Decimal("2000")
    assert recorded_statistics["total_pnl"] is None
    assert recorded_statistics["position_count"] == 2
    assert recorded_statistics["valuation_known"] is False
    assert recorded_statistics["valuation_status"] == "unknown"
