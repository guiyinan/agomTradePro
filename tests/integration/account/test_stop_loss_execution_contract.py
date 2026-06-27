from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from apps.account.application.stop_loss_use_cases import AutoStopLossUseCase
from apps.account.infrastructure.models import (
    PortfolioModel,
    PositionModel,
    StopLossConfigModel,
    StopLossTriggerModel,
    TransactionModel,
)
from apps.account.infrastructure.repositories import PositionRepository, StopLossRepository
from apps.risk_center.infrastructure.models import AccountRiskPolicyModel


class _StaticMarketDataService:
    def get_current_price(self, asset_code: str) -> Decimal:
        return Decimal("8.90")


class _RecordingNotificationService:
    def __init__(self):
        self.stop_loss_notifications = []

    def notify_stop_loss_triggered(self, notification_data) -> bool:
        self.stop_loss_notifications.append(notification_data)
        return True


@pytest.mark.django_db
def test_auto_stop_loss_executes_against_real_repositories():
    user = User.objects.create_user(
        username="stop_loss_contract_owner",
        password="x",
        email="owner@example.com",
    )
    portfolio = PortfolioModel.objects.create(user=user, name="StopLossContract", is_active=True)
    position = PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="600000.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=1000,
        avg_cost=Decimal("10.00"),
        current_price=Decimal("10.00"),
        market_value=Decimal("10000.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        source="manual",
        is_closed=False,
    )
    config = StopLossConfigModel.objects.create(
        position=position,
        stop_loss_type="fixed",
        stop_loss_pct=0.20,
        highest_price=Decimal("10.00"),
        status="active",
    )
    AccountRiskPolicyModel.objects.create(
        account_id=portfolio.id,
        max_stop_loss_pct=0.10,
    )
    notification_service = _RecordingNotificationService()

    results = AutoStopLossUseCase(
        market_data_service=_StaticMarketDataService(),
        notification_service=notification_service,
        stop_loss_repo=StopLossRepository(),
        position_repo=PositionRepository(),
    ).check_and_execute_stop_loss(user_id=user.id)

    assert len(results) == 1
    assert results[0].should_close is True

    position.refresh_from_db()
    config.refresh_from_db()
    assert position.is_closed is True
    assert position.current_price == Decimal("8.9000")
    assert config.status == "triggered"
    assert config.triggered_at is not None

    txn = TransactionModel.objects.get(position_id=position.id, action="sell")
    assert txn.price == Decimal("8.9000")
    assert txn.notes.startswith("止损触发:")

    trigger = StopLossTriggerModel.objects.get(position_id=position.id)
    assert trigger.trigger_price == Decimal("8.9000")
    assert trigger.trigger_type == "fixed"
    assert notification_service.stop_loss_notifications[0].asset_code == "600000.SH"
