from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


@pytest.mark.django_db
def test_risk_center_console_renders_for_staff():
    user = get_user_model().objects.create_user(
        username="risk_page_staff",
        password="pass123456",
        is_staff=True,
    )
    SimulatedAccountModel._default_manager.create(
        user=user,
        account_name="risk page account",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
    )
    client = Client()
    client.force_login(user)

    response = client.get("/risk-center/")

    assert response.status_code == 200
    html = response.content.decode("utf-8")
    assert "集中风控中心" in html
    assert "全局底线" in html
    assert "保存全局底线" in html
    assert "保存账户策略" in html
    assert "预览有效策略" in html
    assert "创建例外" in html
    assert "/api/risk-center/" in html
    assert "/tui/#/risk-center.overview" in html
