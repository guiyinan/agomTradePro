from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.account.application.stop_loss_use_cases import (
    AutoStopLossUseCase,
    CreateStopLossConfigUseCase,
    CreateTakeProfitConfigUseCase,
)
from apps.account.domain.services import StopLossCheckResult


class _FakePositionRepository:
    def __init__(self, position_context: dict | None = None):
        self.position_context = position_context
        self.close_calls: list[dict] = []

    def get_position_stop_management_context(self, position_id: int) -> dict | None:
        return self.position_context

    def close_position(
        self,
        position_id: int,
        shares: float | None = None,
        price: Decimal | None = None,
        reason: str | None = None,
    ) -> dict:
        payload = {
            "position_id": position_id,
            "shares": shares,
            "price": price,
            "reason": reason,
        }
        self.close_calls.append(payload)
        return payload


class _FakeStopLossRepository:
    def __init__(self, active_configs: list[dict] | None = None, existing_config: dict | None = None):
        self.active_configs = active_configs or []
        self.existing_config = existing_config
        self.created_configs: list[dict] = []
        self.updated_configs: list[dict] = []
        self.created_triggers: list[dict] = []

    def get_active_stop_loss_configs(self, user_id: int | None = None) -> list[dict]:
        return self.active_configs

    def get_stop_loss_config_by_position(self, position_id: int) -> dict | None:
        return self.existing_config

    def create_stop_loss_config(self, **kwargs) -> dict:
        payload = {"id": 11, **kwargs, "status": "active"}
        self.created_configs.append(payload)
        return payload

    def update_stop_loss_config(self, config_id: int, **kwargs) -> bool:
        self.updated_configs.append({"config_id": config_id, **kwargs})
        return True

    def create_stop_loss_trigger(self, **kwargs) -> dict:
        self.created_triggers.append(kwargs)
        return {"id": 21, **kwargs}


class _FakeTakeProfitRepository:
    def __init__(self, existing_config: dict | None = None):
        self.existing_config = existing_config
        self.created_configs: list[dict] = []

    def get_take_profit_config_by_position(self, position_id: int) -> dict | None:
        return self.existing_config

    def create_take_profit_config(self, **kwargs) -> dict:
        payload = {"id": 31, **kwargs, "is_active": True}
        self.created_configs.append(payload)
        return payload


class _FakeMarketDataService:
    def get_current_price(self, asset_code: str) -> Decimal | None:
        return Decimal("90")


class _FakeNotificationService:
    def __init__(self):
        self.notifications: list[object] = []

    def notify_stop_loss_triggered(self, notification_data) -> bool:
        self.notifications.append(notification_data)
        return True

    def notify_take_profit_triggered(self, notification_data) -> bool:
        self.notifications.append(notification_data)
        return True


def test_create_stop_loss_config_use_case_uses_repositories():
    position_repo = _FakePositionRepository(
        {
            "id": 1,
            "avg_cost": Decimal("100"),
        }
    )
    stop_loss_repo = _FakeStopLossRepository()

    result = CreateStopLossConfigUseCase(
        position_repo=position_repo,
        stop_loss_repo=stop_loss_repo,
    ).execute(
        position_id=1,
        stop_loss_type="fixed",
        stop_loss_pct=0.1,
    )

    assert result["id"] == 11
    assert stop_loss_repo.created_configs == [
        {
            "id": 11,
            "position_id": 1,
            "stop_loss_type": "fixed",
            "stop_loss_pct": 0.1,
            "trailing_stop_pct": None,
            "max_holding_days": None,
            "highest_price": Decimal("100"),
            "status": "active",
        }
    ]


def test_create_take_profit_config_use_case_rejects_existing_config():
    position_repo = _FakePositionRepository({"id": 1, "avg_cost": Decimal("100")})
    take_profit_repo = _FakeTakeProfitRepository(existing_config={"id": 88})

    with pytest.raises(ValueError, match="已有止盈配置"):
        CreateTakeProfitConfigUseCase(
            position_repo=position_repo,
            take_profit_repo=take_profit_repo,
        ).execute(position_id=1, take_profit_pct=0.2)


def test_auto_stop_loss_use_case_executes_via_repositories(monkeypatch):
    stop_loss_repo = _FakeStopLossRepository(
        active_configs=[
            {
                "id": 7,
                "position_id": 3,
                "stop_loss_type": "fixed",
                "stop_loss_pct": 0.1,
                "trailing_stop_pct": None,
                "max_holding_days": None,
                "highest_price": Decimal("100"),
                "highest_price_updated_at": datetime(2026, 4, 1, tzinfo=UTC),
                "status": "active",
                "position": {
                    "id": 3,
                    "asset_code": "510300.SH",
                    "shares": 200.0,
                    "avg_cost": Decimal("100"),
                    "current_price": Decimal("100"),
                    "opened_at": datetime(2026, 1, 1, tzinfo=UTC),
                    "portfolio_id": 2,
                    "user_id": 9,
                    "user_email": "user@example.com",
                },
            }
        ]
    )
    position_repo = _FakePositionRepository()
    notification_service = _FakeNotificationService()

    monkeypatch.setattr(
        "apps.account.application.stop_loss_use_cases.StopLossService.check_stop_loss",
        lambda **kwargs: StopLossCheckResult(
            should_trigger=True,
            trigger_reason="跌破止损线",
            stop_price=95.0,
            current_price=90.0,
            unrealized_pnl_pct=-0.1,
            highest_price=100.0,
        ),
    )

    use_case = AutoStopLossUseCase(
        market_data_service=_FakeMarketDataService(),
        notification_service=notification_service,
        stop_loss_repo=stop_loss_repo,
        position_repo=position_repo,
    )

    result = use_case.check_and_execute_stop_loss(user_id=9)

    assert len(result) == 1
    assert position_repo.close_calls[0]["position_id"] == 3
    assert "止损触发" in position_repo.close_calls[0]["reason"]
    assert stop_loss_repo.updated_configs[0]["status"] == "triggered"
    assert stop_loss_repo.created_triggers[0]["position_id"] == 3
    assert notification_service.notifications[0].asset_code == "510300.SH"
