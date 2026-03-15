from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.factor.infrastructure.models import (
    FactorPortfolioConfigModel,
    FactorPortfolioHoldingModel,
)


@pytest.mark.django_db
def test_factor_calculate_page_shows_total_stock_count_when_top_n_is_limited():
    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="factor_calculate_page_tester",
        password="StrongPass123!",
        email="factor-calc@test.example",
    )
    client = Client()
    client.force_login(user)

    config = FactorPortfolioConfigModel._default_manager.create(
        name="计算页展示测试配置",
        description="用于验证 total_stocks 展示",
        factor_weights={"roe": 0.5},
        universe="all_a",
        top_n=3,
        rebalance_frequency="monthly",
        weight_method="equal_weight",
        is_active=True,
    )

    trade_date = date(2026, 3, 15)
    for idx in range(1, 4):
        FactorPortfolioHoldingModel._default_manager.create(
            config=config,
            trade_date=trade_date,
            stock_code=f"00000{idx}.SZ",
            stock_name=f"测试股票{idx}",
            weight=0.1 * idx,
            factor_score=100 - idx,
            rank=idx,
            sector="测试行业",
            factor_scores={"roe": 0.5},
        )

    response = client.get(f"/factor/calculate/?config_id={config.id}&top_n=2")

    assert response.status_code == 200
    html = response.content.decode("utf-8")
    assert "仅显示前 2 只股票，共 3 只" in html
