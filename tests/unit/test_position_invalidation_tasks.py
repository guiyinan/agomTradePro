"""Task-level tests for position invalidation workflow."""

from types import SimpleNamespace
from unittest.mock import patch


def test_check_position_invalidation_task_marks_only_without_trade_side_effects():
    task_result = {
        "checked": 3,
        "invalidated": 1,
        "positions": [
            {
                "account_id": 1,
                "asset_code": "000001.SZ",
                "asset_name": "PingAn",
                "reason": "PMI 跌破 50",
            }
        ],
    }

    with (
        patch(
            "apps.simulated_trading.application.position_invalidation_checker.check_and_invalidate_positions",
            return_value=task_result,
        ) as checker_mock,
        patch("apps.simulated_trading.application.tasks.AutoTradingEngine") as engine_cls,
        patch("apps.simulated_trading.application.tasks.ExecuteSellOrderUseCase") as sell_use_case_cls,
    ):
        from apps.simulated_trading.application.tasks import check_position_invalidation_task

        result = check_position_invalidation_task.run()

    assert result == {
        "success": True,
        "checked": 3,
        "invalidated": 1,
        "positions": task_result["positions"],
    }
    checker_mock.assert_called_once_with()
    engine_cls.assert_not_called()
    sell_use_case_cls.assert_not_called()


def test_notify_invalidated_positions_task_sends_notifications_without_trade_side_effects():
    positions = [
        {
            "account_name": "Demo",
            "asset_code": "000001.SZ",
            "asset_name": "PingAn",
            "quantity": 100,
            "invalidation_reason": "PMI 跌破 50",
        }
    ]
    notification_service = SimpleNamespace(
        send_email=lambda **kwargs: [
            SimpleNamespace(
                recipient=SimpleNamespace(email="ops@example.com"),
                success=True,
            )
        ]
    )

    with (
        patch(
            "apps.simulated_trading.application.position_invalidation_checker.get_invalidated_positions_summary",
            return_value=positions,
        ) as summary_mock,
        patch(
            "shared.infrastructure.notification_service.get_notification_service",
            return_value=notification_service,
        ) as notification_service_mock,
        patch(
            "apps.simulated_trading.application.tasks.settings.INVALIDATION_ALERT_RECIPIENTS",
            ["ops@example.com"],
            create=True,
        ),
        patch("apps.simulated_trading.application.tasks.AutoTradingEngine") as engine_cls,
        patch("apps.simulated_trading.application.tasks.ExecuteSellOrderUseCase") as sell_use_case_cls,
    ):
        from apps.simulated_trading.application.tasks import notify_invalidated_positions_task

        result = notify_invalidated_positions_task.run()

    assert result == {
        "success": True,
        "count": 1,
        "positions": positions,
        "notifications": [{"email": "ops@example.com", "success": True}],
    }
    summary_mock.assert_called_once_with()
    notification_service_mock.assert_called_once_with()
    engine_cls.assert_not_called()
    sell_use_case_cls.assert_not_called()


def test_notify_invalidated_positions_task_skips_notifications_when_no_positions():
    with (
        patch(
            "apps.simulated_trading.application.position_invalidation_checker.get_invalidated_positions_summary",
            return_value=[],
        ) as summary_mock,
        patch(
            "shared.infrastructure.notification_service.get_notification_service",
        ) as notification_service_mock,
        patch("apps.simulated_trading.application.tasks.AutoTradingEngine") as engine_cls,
        patch("apps.simulated_trading.application.tasks.ExecuteSellOrderUseCase") as sell_use_case_cls,
    ):
        from apps.simulated_trading.application.tasks import notify_invalidated_positions_task

        result = notify_invalidated_positions_task.run()

    assert result == {
        "success": True,
        "count": 0,
        "positions": [],
        "notifications": [],
    }
    summary_mock.assert_called_once_with()
    notification_service_mock.assert_not_called()
    engine_cls.assert_not_called()
    sell_use_case_cls.assert_not_called()
