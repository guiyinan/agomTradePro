from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from apps.account.application.stop_loss_use_cases import (
    AutoStopLossUseCase,
    AutoTakeProfitUseCase,
)
from apps.account.infrastructure.models import (
    PortfolioModel,
    PositionModel,
    StopLossConfigModel,
    StopLossTriggerModel,
    TakeProfitConfigModel,
    TransactionModel,
)
from apps.account.infrastructure.repositories import StopLossRepository, TakeProfitRepository
from apps.risk_center.infrastructure.models import AccountRiskPolicyModel


class _StaticMarketPriceService:
    def __init__(self, price: str, observed_at: datetime | None = None) -> None:
        self.price = Decimal(price)
        self.observed_at = observed_at or timezone.now() - timedelta(seconds=1)
        self.scalar_calls: list[str] = []

    def get_current_price(self, asset_code: str) -> Decimal:
        """Keep the legacy scalar seam executable so RED reaches its write behavior."""

        self.scalar_calls.append(asset_code)
        return self.price

    def get_price_with_metadata(self, asset_code: str) -> dict[str, object]:
        return {
            "price": self.price,
            "asset_code": asset_code,
            "source": "integration_quote_fixture",
            "timestamp": self.observed_at,
            "observed_at": self.observed_at,
            "trade_date": None,
            "requested_trade_date": None,
            "freshness": "realtime",
            "is_fallback": False,
        }


def _create_position(user: User, *, name: str, shares: int) -> PositionModel:
    """Create one legacy account position for a repository-backed negative test."""

    portfolio = PortfolioModel.objects.create(user=user, name=name, is_active=True)
    return PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="600000.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=shares,
        avg_cost=Decimal("10.00"),
        current_price=Decimal("10.00"),
        market_value=Decimal(str(shares * 10)),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        source="manual",
        is_closed=False,
    )


def _snapshot_model(instance: object) -> dict[str, object]:
    """Capture every persisted concrete field for an ORM row."""

    model = instance.__class__
    return {
        field.attname: getattr(instance, field.attname) for field in model._meta.concrete_fields
    }


def _account_ledger_snapshot(portfolio: PortfolioModel) -> dict[str, object]:
    """Capture portfolio, all positions, all transactions, and all stop triggers."""

    portfolio.refresh_from_db()
    return {
        "portfolio": _snapshot_model(portfolio),
        "positions": list(
            PositionModel.objects.filter(portfolio=portfolio).order_by("pk").values()
        ),
        "transactions": list(
            TransactionModel.objects.filter(portfolio=portfolio).order_by("pk").values()
        ),
        "stop_loss_triggers": list(
            StopLossTriggerModel.objects.filter(position__portfolio=portfolio)
            .order_by("pk")
            .values()
        ),
    }


@pytest.mark.django_db
def test_fixed_stop_trigger_is_observation_only_across_full_account_ledger() -> None:
    user = User.objects.create_user(
        username="stop_loss_contract_owner",
        password="x",
        email="owner@example.com",
    )
    position = _create_position(user, name="StopLossContract", shares=1000)
    portfolio = position.portfolio
    config = StopLossConfigModel.objects.create(
        position=position,
        stop_loss_type="fixed",
        stop_loss_pct=0.20,
        highest_price=Decimal("10.00"),
        status="active",
    )
    AccountRiskPolicyModel.objects.create(account_id=portfolio.id, max_stop_loss_pct=0.10)
    before_ledger = _account_ledger_snapshot(portfolio)
    before_config = _snapshot_model(config)

    market = _StaticMarketPriceService("8.90")
    results = AutoStopLossUseCase(
        market_data_service=market,
        stop_loss_repo=StopLossRepository(),
    ).check_and_execute_stop_loss(user_id=user.id)

    config.refresh_from_db()
    assert _account_ledger_snapshot(portfolio) == before_ledger
    assert _snapshot_model(config) == before_config

    assert len(results) == 1
    assert results[0].triggered is True
    assert results[0].execution_status == "blocked"
    assert results[0].reason_code == "legacy_automatic_exit_not_qualified"
    assert results[0].price_source == "integration_quote_fixture"
    assert results[0].price_freshness == "realtime"
    assert results[0].price_observed_at is not None
    assert results[0].must_not_use_for_decision is True
    assert results[0].must_not_execute is True
    assert market.scalar_calls == []


@pytest.mark.django_db
def test_fixed_take_profit_trigger_leaves_full_account_ledger_and_config_unchanged() -> None:
    user = User.objects.create_user(
        username="take_profit_contract_owner",
        password="x",
        email="owner@example.com",
    )
    position = _create_position(user, name="TakeProfitContract", shares=900)
    portfolio = position.portfolio
    config = TakeProfitConfigModel.objects.create(
        position=position,
        take_profit_pct=0.40,
        partial_profit_levels=[0.10, 0.20, 0.30],
        is_active=True,
    )
    before_ledger = _account_ledger_snapshot(portfolio)
    before_config = _snapshot_model(config)

    market = _StaticMarketPriceService("13.00")
    results = AutoTakeProfitUseCase(
        market_data_service=market,
        take_profit_repo=TakeProfitRepository(),
    ).check_and_execute_take_profit(user_id=user.id)

    config.refresh_from_db()
    assert _account_ledger_snapshot(portfolio) == before_ledger
    assert _snapshot_model(config) == before_config

    assert len(results) == 1
    assert results[0].triggered is True
    assert results[0].execution_status == "blocked"
    assert results[0].reason_code == "legacy_automatic_exit_not_qualified"
    assert results[0].partial_level == 1
    assert results[0].price_source == "integration_quote_fixture"
    assert results[0].price_freshness == "realtime"
    assert results[0].must_not_execute is True
    assert market.scalar_calls == []


@pytest.mark.django_db
def test_trailing_peak_uses_source_time_and_only_whitelisted_config_fields_change() -> None:
    user = User.objects.create_user(
        username="trailing_contract_owner",
        password="x",
        email="owner@example.com",
    )
    position = _create_position(user, name="TrailingContract", shares=1000)
    portfolio = position.portfolio
    source_observed_at = datetime(2026, 4, 1, tzinfo=UTC)
    config = StopLossConfigModel.objects.create(
        position=position,
        stop_loss_type="trailing",
        stop_loss_pct=0.20,
        trailing_stop_pct=0.10,
        highest_price=Decimal("10.00"),
        highest_price_updated_at=datetime(2026, 3, 1, tzinfo=UTC),
        status="active",
    )
    before_ledger = _account_ledger_snapshot(portfolio)
    before_config = _snapshot_model(config)

    market = _StaticMarketPriceService("11.00", source_observed_at)
    results = AutoStopLossUseCase(
        market_data_service=market,
        stop_loss_repo=StopLossRepository(),
    ).check_and_execute_stop_loss(user_id=user.id)

    config.refresh_from_db()
    after_config = _snapshot_model(config)
    for allowed_field in ("highest_price", "highest_price_updated_at", "updated_at"):
        before_config.pop(allowed_field)
        after_config.pop(allowed_field)
    assert after_config == before_config
    assert config.highest_price == Decimal("11.0000")
    assert config.highest_price_updated_at == source_observed_at
    assert _account_ledger_snapshot(portfolio) == before_ledger

    assert len(results) == 1
    assert results[0].triggered is False
    assert results[0].execution_status == "not_triggered"
    assert results[0].price_observed_at == source_observed_at
    assert market.scalar_calls == []
