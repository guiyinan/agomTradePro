from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="fund_user",
        password="testpass123",
        email="fund@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_fund_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/fund/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["screen"] == "/api/fund/screen/"
    assert payload["endpoints"]["multidim_screen"] == "/api/fund/multidim-screen/"


@pytest.mark.django_db
def test_fund_style_returns_404_when_use_case_reports_missing_fund(authenticated_client):
    response_obj = type(
        "FundStyleResponse",
        (),
        {
            "success": False,
            "fund_code": "000001",
            "fund_name": "",
            "style_weights": {},
            "sector_concentration": {},
            "error": "fund not found",
        },
    )()

    with patch("apps.fund.interface.views.AnalyzeFundStyleUseCase.execute", return_value=response_obj):
        response = authenticated_client.get("/api/fund/style/000001/")

    assert response.status_code == 404
    assert response.json()["success"] is False
    assert response.json()["error"] == "fund not found"


@pytest.mark.django_db
def test_fund_multidim_screen_returns_500_on_exception(authenticated_client):
    with patch("apps.fund.application.services.FundMultiDimScorer.screen_funds", side_effect=RuntimeError("boom")):
        response = authenticated_client.post(
            "/api/fund/multidim-screen/",
            {
                "filters": {"fund_type": "股票型"},
                "context": {"regime": "Recovery", "policy_level": "P0", "sentiment_index": 0.1},
                "max_count": 10,
            },
            format="json",
        )

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert "筛选失败" in payload["message"]
