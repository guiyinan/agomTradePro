import pytest
from django.contrib.auth.models import User
from django.test import Client
from rest_framework.test import APIClient

from apps.account.infrastructure.models import PortfolioModel, TradingCostConfigModel


@pytest.fixture
def trading_cost_setup(db):
    owner = User.objects.create_user(
        username="trading_owner",
        email="owner@example.com",
        password="testpass123",
    )
    other_user = User.objects.create_user(
        username="trading_other",
        email="other@example.com",
        password="testpass123",
    )
    portfolio = PortfolioModel.objects.create(
        user=owner,
        name="Owner Portfolio",
        is_active=True,
    )
    other_portfolio = PortfolioModel.objects.create(
        user=other_user,
        name="Other Portfolio",
        is_active=True,
    )
    config = TradingCostConfigModel.objects.create(
        portfolio=portfolio,
        commission_rate=0.00025,
        min_commission=5.0,
        stamp_duty_rate=0.001,
        transfer_fee_rate=0.00002,
        is_active=True,
    )
    return {
        "owner": owner,
        "other_user": other_user,
        "portfolio": portfolio,
        "other_portfolio": other_portfolio,
        "config": config,
    }


@pytest.mark.django_db
class TestTradingCostConfigApi:
    def test_cannot_move_config_to_another_portfolio(self, trading_cost_setup):
        client = APIClient()
        client.force_authenticate(user=trading_cost_setup["owner"])

        response = client.patch(
            f'/account/api/trading-cost-configs/{trading_cost_setup["config"].id}/',
            {"portfolio": trading_cost_setup["other_portfolio"].id},
            format="json",
        )

        assert response.status_code == 400
        assert "portfolio" in response.data["details"]

        trading_cost_setup["config"].refresh_from_db()
        assert trading_cost_setup["config"].portfolio_id == trading_cost_setup["portfolio"].id

    def test_calculate_rejects_non_numeric_amount(self, trading_cost_setup):
        client = APIClient()
        client.force_authenticate(user=trading_cost_setup["owner"])

        response = client.post(
            f'/account/api/trading-cost-configs/{trading_cost_setup["config"].id}/calculate/',
            {"action": "buy", "amount": "abc", "is_shanghai": False},
            format="json",
        )

        assert response.status_code == 400
        assert "amount" in response.data["details"]

    def test_calculate_treats_form_false_as_false(self, trading_cost_setup):
        client = APIClient()
        client.force_authenticate(user=trading_cost_setup["owner"])

        response = client.post(
            f'/account/api/trading-cost-configs/{trading_cost_setup["config"].id}/calculate/',
            {"action": "buy", "amount": "100000", "is_shanghai": "false"},
        )

        assert response.status_code == 200
        assert response.data["data"]["transfer_fee"] == 0.0
        assert response.data["data"]["total"] == 25.0


@pytest.mark.django_db
class TestTradingCostConfigSettingsView:
    def test_settings_view_rejects_invalid_trading_cost(self, trading_cost_setup):
        client = Client()
        client.force_login(trading_cost_setup["owner"])

        response = client.post(
            "/account/settings/",
            {
                "display_name": "Owner",
                "risk_tolerance": "moderate",
                "email": "owner@example.com",
                "save_trading_cost": "1",
                "commission_rate": "-0.1",
                "min_commission": "5",
                "stamp_duty_rate": "0.001",
                "transfer_fee_rate": "0.00002",
            },
        )

        assert response.status_code == 302

        trading_cost_setup["config"].refresh_from_db()
        assert trading_cost_setup["config"].commission_rate == 0.00025
