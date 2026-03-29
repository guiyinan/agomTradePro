"""Regression tests for strategy binding atomicity."""

import json
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import TestCase

from apps.account.infrastructure.models import AccountProfileModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.strategy.infrastructure.models import PortfolioStrategyAssignmentModel, StrategyModel


@pytest.mark.django_db
class TestStrategyBindingConsistency(TestCase):
    """Verify strategy binding and unbinding preserve a consistent active state."""

    def setUp(self) -> None:
        unique_id = str(uuid.uuid4())[:8]
        self.user = User.objects.create_user(
            username=f"strategy_bind_{unique_id}",
            password="pass123456",
        )
        self.profile = AccountProfileModel.objects.get(user=self.user)
        self.client.force_login(self.user)
        self.portfolio = SimulatedAccountModel.objects.create(
            user=self.user,
            account_name="测试组合",
            account_type="simulated",
            initial_capital=Decimal("100000.00"),
            current_cash=Decimal("100000.00"),
            current_market_value=Decimal("0"),
            total_value=Decimal("100000.00"),
            auto_trading_enabled=True,
        )
        self.strategy_a = StrategyModel.objects.create(
            name="策略A",
            strategy_type="rule_based",
            version=1,
            is_active=True,
            description="A",
            max_position_pct=20.0,
            max_total_position_pct=95.0,
            stop_loss_pct=10.0,
            created_by=self.profile,
        )
        self.strategy_b = StrategyModel.objects.create(
            name="策略B",
            strategy_type="rule_based",
            version=1,
            is_active=True,
            description="B",
            max_position_pct=20.0,
            max_total_position_pct=95.0,
            stop_loss_pct=10.0,
            created_by=self.profile,
        )

    def test_bind_strategy_deactivates_previous_assignment(self) -> None:
        """Rebinding should leave exactly one active assignment for the portfolio."""
        PortfolioStrategyAssignmentModel.objects.create(
            portfolio=self.portfolio,
            strategy=self.strategy_a,
            assigned_by=self.profile,
            is_active=True,
        )

        response = self.client.post(
            "/api/strategy/bind-strategy/",
            data=json.dumps(
                {
                    "portfolio_id": self.portfolio.id,
                    "strategy_id": self.strategy_b.id,
                }
            ),
            content_type="application/json",
        )

        active_assignments = list(
            PortfolioStrategyAssignmentModel.objects.filter(
                portfolio=self.portfolio,
                is_active=True,
            ).values_list("strategy_id", flat=True)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(active_assignments, [self.strategy_b.id])
        self.assertFalse(
            PortfolioStrategyAssignmentModel.objects.get(
                portfolio=self.portfolio,
                strategy=self.strategy_a,
            ).is_active
        )

    def test_bind_strategy_rolls_back_when_new_assignment_creation_fails(self) -> None:
        """A failed bind should keep the prior active assignment untouched."""
        PortfolioStrategyAssignmentModel.objects.create(
            portfolio=self.portfolio,
            strategy=self.strategy_a,
            assigned_by=self.profile,
            is_active=True,
        )

        with patch.object(
            PortfolioStrategyAssignmentModel,
            "save",
            autospec=True,
            side_effect=RuntimeError("boom"),
        ):
            response = self.client.post(
                "/api/strategy/bind-strategy/",
                data=json.dumps(
                    {
                        "portfolio_id": self.portfolio.id,
                        "strategy_id": self.strategy_b.id,
                    }
                ),
                content_type="application/json",
            )

        assignment_a = PortfolioStrategyAssignmentModel.objects.get(
            portfolio=self.portfolio,
            strategy=self.strategy_a,
        )

        self.assertEqual(response.status_code, 500)
        self.assertTrue(assignment_a.is_active)
        self.assertFalse(
            PortfolioStrategyAssignmentModel.objects.filter(
                portfolio=self.portfolio,
                strategy=self.strategy_b,
            ).exists()
        )

    def test_unbind_strategy_keeps_existing_assignment_if_internal_error_occurs(self) -> None:
        """An unbind failure should not silently clear the active assignment."""
        assignment = PortfolioStrategyAssignmentModel.objects.create(
            portfolio=self.portfolio,
            strategy=self.strategy_a,
            assigned_by=self.profile,
            is_active=True,
        )

        with patch(
            "apps.strategy.interface.views.PortfolioStrategyAssignmentModel._default_manager.select_for_update",
            side_effect=RuntimeError("boom"),
        ):
            response = self.client.post(
                "/api/strategy/unbind-strategy/",
                data=json.dumps({"portfolio_id": self.portfolio.id}),
                content_type="application/json",
            )

        assignment.refresh_from_db()

        self.assertEqual(response.status_code, 500)
        self.assertTrue(assignment.is_active)
