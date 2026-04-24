from decimal import Decimal
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.account.infrastructure.models import (
    AccountProfileModel,
    AssetCategoryModel,
    CurrencyModel,
    ExchangeRateModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    user = get_user_model().objects.create_user(
        username="account_api_user",
        password="testpass123",
        email="account@example.com",
    )
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": "Account API User",
            "initial_capital": Decimal("1000000.00"),
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
        },
    )
    return user


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_account_health_contract(authenticated_client):
    response = authenticated_client.get("/api/account/health/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["service"] == "account"


@pytest.mark.django_db
def test_account_user_search_short_query_returns_empty(authenticated_client):
    response = authenticated_client.get("/api/account/users/search/?q=a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["results"] == []


@pytest.mark.django_db
def test_account_sizing_context_rejects_invalid_portfolio_id(authenticated_client):
    response = authenticated_client.get("/api/account/sizing-context/?portfolio_id=bad")

    assert response.status_code == 400
    assert response.json()["detail"] == "portfolio_id 必须为整数"


@pytest.mark.django_db
def test_account_portfolio_allocation_returns_404_for_missing_portfolio(authenticated_client):
    response = authenticated_client.get("/api/account/portfolios/999999/allocation/")

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert "Portfolio not found" in payload["error"]


@pytest.mark.django_db
def test_account_portfolio_allocation_category_contract(authenticated_client, auth_user):
    portfolio = PortfolioModel.objects.create(user=auth_user, name="API Portfolio", is_active=True)

    response = authenticated_client.get(f"/api/account/portfolios/{portfolio.id}/allocation/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["dimension"] == "category"


@pytest.mark.django_db
def test_account_category_roots_contract(authenticated_client):
    root = AssetCategoryModel.objects.create(
        code="fund_root",
        name="基金",
        level=1,
        path="基金",
        is_active=True,
        sort_order=1,
    )
    AssetCategoryModel.objects.create(
        code="bond_fund",
        name="债券基金",
        parent=root,
        level=2,
        path="基金/债券基金",
        is_active=True,
        sort_order=1,
    )

    response = authenticated_client.get("/api/account/categories/roots/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"][0]["code"] == "fund_root"


@pytest.mark.django_db
def test_account_currency_base_contract(authenticated_client):
    CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )

    response = authenticated_client.get("/api/account/currencies/base/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "CNY"
    assert payload["is_base"] is True


@pytest.mark.django_db
def test_account_exchange_rate_latest_contract(authenticated_client):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    cny = CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )
    ExchangeRateModel.objects.create(
        from_currency=usd,
        to_currency=cny,
        rate=Decimal("7.123400"),
        effective_date=date(2026, 4, 1),
    )

    response = authenticated_client.get("/api/account/exchange-rates/latest/USD/CNY/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["from_currency_code"] == "USD"
    assert payload["to_currency_code"] == "CNY"
    assert Decimal(str(payload["rate"])) == Decimal("7.123400")


@pytest.mark.django_db
def test_account_exchange_rate_convert_contract(authenticated_client):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    cny = CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )
    ExchangeRateModel.objects.create(
        from_currency=usd,
        to_currency=cny,
        rate=Decimal("7.123400"),
        effective_date=date(2026, 4, 1),
    )

    response = authenticated_client.post(
        "/api/account/exchange-rates/convert/",
        {
            "amount": "100.00",
            "from_currency": "USD",
            "to_currency": "CNY",
            "date": "2026-04-01",
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert Decimal(str(payload["converted_amount"])) == Decimal("712.340000")
    assert Decimal(str(payload["rate_used"])) == Decimal("7.123400")
    assert payload["rate_date"] == "2026-04-01"


@pytest.mark.django_db
def test_account_portfolio_allocation_currency_contract(authenticated_client, auth_user):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    cny = CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )
    portfolio = PortfolioModel.objects.create(
        user=auth_user,
        name="Currency Allocation Portfolio",
        is_active=True,
        base_currency=cny,
    )
    PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="SPY",
        asset_class="equity",
        region="US",
        cross_border="cross_border",
        shares=10,
        avg_cost=Decimal("50.0000"),
        current_price=Decimal("52.0000"),
        market_value=Decimal("520.00"),
        unrealized_pnl=Decimal("20.00"),
        unrealized_pnl_pct=4.0,
        currency=usd,
    )
    ExchangeRateModel.objects.create(
        from_currency=usd,
        to_currency=cny,
        rate=Decimal("7.200000"),
        effective_date=date(2026, 4, 1),
    )

    response = authenticated_client.get(
        f"/api/account/portfolios/{portfolio.id}/allocation/?dimension=currency"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["dimension"] == "currency"
    assert payload["base_currency"] == "CNY"
    assert payload["data"][0]["currency_code"] == "USD"


@pytest.mark.django_db
def test_account_observer_positions_allows_observer_without_as_observer_query_param(
    authenticated_client, auth_user
):
    owner = get_user_model().objects.create_user(
        username="observer_owner",
        password="testpass123",
        email="owner@example.com",
    )
    AccountProfileModel.objects.update_or_create(
        user=owner,
        defaults={
            "display_name": "Observer Owner",
            "initial_capital": Decimal("500000.00"),
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
        },
    )
    portfolio = PortfolioModel.objects.create(user=owner, name="Observer Portfolio", is_active=True)
    PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="000001.SZ",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=100,
        avg_cost=Decimal("10.0000"),
        current_price=Decimal("12.0000"),
        market_value=Decimal("1200.00"),
        unrealized_pnl=Decimal("200.00"),
        unrealized_pnl_pct=20.0,
    )
    grant = PortfolioObserverGrantModel.objects.create(
        owner_user_id=owner,
        observer_user_id=auth_user,
        expires_at=timezone.now() + timedelta(days=7),
    )

    response = authenticated_client.get(f"/api/account/observer-grants/{grant.id}/positions/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["positions"][0]["asset_code"] == "000001.SZ"
    assert payload["data"]["positions"][0]["asset_name"] == "000001.SZ"


@pytest.mark.django_db
def test_account_observer_detail_allows_observer_without_as_observer_query_param(
    authenticated_client, auth_user
):
    owner = get_user_model().objects.create_user(
        username="detail_owner",
        password="testpass123",
        email="detail-owner@example.com",
    )
    grant = PortfolioObserverGrantModel.objects.create(
        owner_user_id=owner,
        observer_user_id=auth_user,
        expires_at=timezone.now() + timedelta(days=7),
    )

    response = authenticated_client.get(f"/api/account/observer-grants/{grant.id}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(grant.id)
    assert payload["observer_username"] == auth_user.username


@pytest.mark.django_db
def test_account_observer_positions_forbid_owner_view(authenticated_client, auth_user):
    observer = get_user_model().objects.create_user(
        username="positions_observer",
        password="testpass123",
        email="positions-observer@example.com",
    )
    grant = PortfolioObserverGrantModel.objects.create(
        owner_user_id=auth_user,
        observer_user_id=observer,
        expires_at=timezone.now() + timedelta(days=7),
    )

    response = authenticated_client.get(f"/api/account/observer-grants/{grant.id}/positions/")

    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert "无权查看" in payload["error"]


@pytest.mark.django_db
def test_account_transaction_create_returns_403_for_foreign_position(authenticated_client):
    other_user = get_user_model().objects.create_user(
        username="foreign_position_owner",
        password="testpass123",
        email="foreign-position@example.com",
    )
    portfolio = PortfolioModel.objects.create(user=other_user, name="Foreign Portfolio", is_active=True)
    position = PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="600000.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=200,
        avg_cost=Decimal("9.0000"),
        current_price=Decimal("9.5000"),
        market_value=Decimal("1900.00"),
        unrealized_pnl=Decimal("100.00"),
        unrealized_pnl_pct=5.0,
    )

    response = authenticated_client.post(
        "/api/account/transactions/",
        {
            "portfolio": portfolio.id,
            "position": position.id,
            "action": "buy",
            "asset_code": "600000.SH",
            "shares": 10,
            "price": "9.5000",
            "commission": "1.00",
            "notes": "edge case",
            "traded_at": timezone.now().isoformat(),
        },
        format="json",
    )

    assert response.status_code == 403
    payload = response.json()
    message = str(payload.get("detail") or payload.get("error") or payload)
    assert "无权为此持仓创建交易记录" in message


@pytest.mark.django_db
def test_account_capital_flow_create_returns_404_for_foreign_portfolio(authenticated_client):
    other_user = get_user_model().objects.create_user(
        username="foreign_portfolio_owner",
        password="testpass123",
        email="foreign-portfolio@example.com",
    )
    portfolio = PortfolioModel.objects.create(user=other_user, name="Foreign Capital Portfolio", is_active=True)

    response = authenticated_client.post(
        "/api/account/capital-flows/",
        {
            "portfolio": portfolio.id,
            "flow_type": "deposit",
            "amount": "1000.00",
            "flow_date": "2026-04-02",
            "notes": "foreign portfolio",
        },
        format="json",
    )

    assert response.status_code == 404
