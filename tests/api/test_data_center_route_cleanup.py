from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.macro.infrastructure.models import MacroIndicator as LegacyMacroIndicatorModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="market_data_api_user",
        password="testpass123",
        email="market-data@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_data_center_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/data-center/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["providers"] == "/api/data-center/providers/"
    assert payload["endpoints"]["price_quotes"] == "/api/data-center/prices/quotes/"


@pytest.mark.django_db
def test_data_center_quotes_require_asset_code(authenticated_client):
    response = authenticated_client.get("/api/data-center/prices/quotes/")

    assert response.status_code == 400
    assert "asset_code" in response.json()["detail"]


@pytest.mark.django_db
def test_data_center_capital_flows_require_asset_code(authenticated_client):
    response = authenticated_client.get("/api/data-center/capital-flows/")

    assert response.status_code == 400
    assert "asset_code" in response.json()["detail"]


@pytest.mark.django_db
def test_legacy_market_data_api_routes_are_removed(authenticated_client):
    response = authenticated_client.get("/api/market-data/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_data_center_macro_series_falls_back_to_legacy_macro_storage(authenticated_client):
    LegacyMacroIndicatorModel.objects.create(
        code="CN_PMI",
        value=50.9,
        unit="指数",
        original_unit="指数",
        reporting_period=date(2025, 3, 1),
        period_type="M",
        published_at=date(2025, 3, 2),
        source="akshare",
    )

    response = authenticated_client.get(
        "/api/data-center/macro/series/?indicator_code=CN_PMI"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["data"][0]["value"] == 50.9


@pytest.mark.django_db
def test_data_center_quotes_fall_back_to_realtime_use_case(authenticated_client, mocker):
    mocker.patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase.get_latest_prices",
        return_value=[
            {
                "asset_code": "510300.SH",
                "asset_type": "etf",
                "price": 3.91,
                "change": 0.02,
                "change_pct": 0.51,
                "volume": 123456,
                "timestamp": "2026-04-06T09:35:00+08:00",
                "source": "akshare",
            }
        ],
    )

    response = authenticated_client.get(
        "/api/data-center/prices/quotes/?asset_code=510300.SH"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_code"] == "510300.SH"
    assert payload["current_price"] == 3.91
    assert payload["source"] == "akshare"
