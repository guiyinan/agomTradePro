from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.equity.infrastructure.models import StockInfoModel
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
    assert response["Content-Type"].startswith("text/html")
    html = response.content.decode("utf-8")
    assert "<h1>因子计算</h1>" in html
    assert 'id="configSelect"' in html
    assert 'id="tradeDateInput"' in html
    assert 'id="topNInput"' in html
    assert f'<option value="{config.id}" selected>' in html
    assert 'class="results-table"' in html
    assert "计算结果 - 计算页展示测试配置" in html
    assert "股票数量: 3" in html
    assert "Top N: 2" in html
    assert "测试股票1" in html
    detail_link = 'href="/equity/detail/000001.SZ/" target="_blank" rel="noopener noreferrer"'
    assert detail_link in html
    assert "测试股票2" in html
    assert "仅显示前 2 只股票，共 3 只" in html


@pytest.mark.django_db
def test_factor_calculate_page_can_select_inactive_config_from_url():
    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="factor_calculate_inactive_tester",
        password="StrongPass123!",
        email="factor-calc-inactive@test.example",
    )
    client = Client()
    client.force_login(user)

    config = FactorPortfolioConfigModel._default_manager.create(
        name="已禁用但可查看配置",
        description="用于验证计算页可以打开禁用配置",
        factor_weights={"roe": 1.0},
        universe="all_a",
        top_n=3,
        rebalance_frequency="monthly",
        weight_method="equal_weight",
        is_active=False,
    )

    response = client.get(f"/factor/calculate/?config_id={config.id}&top_n=2")

    assert response.status_code == 200
    html = response.content.decode("utf-8")
    assert f'<option value="{config.id}" selected>' in html
    assert "已禁用但可查看配置" in html
    assert "- 禁用" in html


@pytest.mark.django_db
def test_factor_calculate_page_fills_missing_stock_name_from_equity_master_data():
    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="factor_calculate_stock_name_tester",
        password="StrongPass123!",
        email="factor-calc-stock-name@test.example",
    )
    client = Client()
    client.force_login(user)

    StockInfoModel._default_manager.create(
        stock_code="000888.SZ",
        name="真实股票名",
        sector="真实行业",
        market="SZ",
        list_date=date(2020, 1, 1),
        is_active=True,
    )
    config = FactorPortfolioConfigModel._default_manager.create(
        name="股票名补齐配置",
        description="用于验证持仓名称展示",
        factor_weights={"roe": 1.0},
        universe="all_a",
        top_n=1,
        rebalance_frequency="monthly",
        weight_method="equal_weight",
        is_active=True,
    )
    FactorPortfolioHoldingModel._default_manager.create(
        config=config,
        trade_date=date(2026, 3, 15),
        stock_code="000888.SZ",
        stock_name="",
        weight=1,
        factor_score=88,
        rank=1,
        sector="",
        factor_scores={"roe": 0.5},
    )

    response = client.get(f"/factor/calculate/?config_id={config.id}&top_n=1")

    assert response.status_code == 200
    html = response.content.decode("utf-8")
    assert "真实股票名" in html
    assert "真实行业" in html
    detail_link = 'href="/equity/detail/000888.SZ/" target="_blank" rel="noopener noreferrer"'
    assert detail_link in html
