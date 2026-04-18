from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


def _response_text(response) -> str:
    return response.content.decode("utf-8")


def _assert_profile_page_contract(response) -> str:
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    content = _response_text(response)
    for fragment in (
        "我的账户 - AgomTradePro",
        "<h1>我的账户</h1>",
        "账户概览",
        "我的投资组合",
        "波动率分析",
        "管理我的投资组合",
        'id="volatilityChart"',
        "/account/settings/",
        "/backtest/create/",
    ):
        assert fragment in content
    return content


@pytest.mark.django_db
def test_profile_view_renders_investment_accounts_without_interface_cross_imports():
    user = get_user_model().objects.create_user(
        username="profile_view_user",
        email="profile-view@example.com",
        password="testpass123",
    )
    SimulatedAccountModel.objects.create(
        user=user,
        account_name="真实账户A",
        account_type="real",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("95000.00"),
        total_value=Decimal("105000.00"),
        total_return=5.0,
        start_date=timezone.now().date(),
    )
    SimulatedAccountModel.objects.create(
        user=user,
        account_name="模拟账户B",
        account_type="simulated",
        initial_capital=Decimal("50000.00"),
        current_cash=Decimal("25000.00"),
        current_market_value=Decimal("26000.00"),
        total_value=Decimal("51000.00"),
        total_return=2.0,
        start_date=timezone.now().date(),
    )

    client = Client()
    client.force_login(user)

    response = client.get("/account/profile/")

    content = _assert_profile_page_contract(response)
    assert "真实账户A" in content
    assert "模拟账户B" in content
    assert "156000.00" in content
