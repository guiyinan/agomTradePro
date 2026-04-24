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
        username="hedge_user",
        password="testpass123",
        email="hedge@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_pairs_correlation_matrix_uses_asset_codes_and_window_days(authenticated_client):
    with patch(
        "apps.hedge.interface.views.interface_services.get_correlation_matrix_payload",
        return_value={
            "asset_codes": ["510300", "511260"],
            "window_days": 30,
            "matrix": [[1.0, -0.42], [-0.42, 1.0]],
        },
    ) as mock_matrix:
        response = authenticated_client.post(
            "/api/hedge/pairs/correlation_matrix/",
            {"asset_codes": ["510300", "511260"], "window_days": 30},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_codes"] == ["510300", "511260"]
    assert payload["window_days"] == 30
    assert payload["matrix"] == [[1.0, -0.42], [-0.42, 1.0]]
    mock_matrix.assert_called_once_with(asset_codes=["510300", "511260"], window_days=30)


@pytest.mark.django_db
def test_actions_check_hedge_ratio_requires_pair_name(authenticated_client):
    response = authenticated_client.post("/api/hedge/actions/check_hedge_ratio/", {}, format="json")

    assert response.status_code == 400
    assert response.json()["error"] == "pair_name is required"


@pytest.mark.django_db
def test_actions_check_hedge_ratio_returns_not_found_for_unknown_pair(authenticated_client):
    with patch(
        "apps.hedge.interface.views.interface_services.get_hedge_ratio_payload",
        return_value=None,
    ) as mock_ratio:
        response = authenticated_client.post(
            "/api/hedge/actions/check_hedge_ratio/",
            {"pair_name": "missing-pair"},
            format="json",
        )

    assert response.status_code == 404
    assert response.json()["error"] == "Hedge pair not found: missing-pair"
    mock_ratio.assert_called_once_with(pair_name="missing-pair")


@pytest.mark.django_db
def test_actions_calculate_correlation_returns_metric_payload(authenticated_client):
    with patch(
        "apps.hedge.interface.views.interface_services.get_correlation_metric_payload",
        return_value={
            "asset1": "510300",
            "asset2": "511260",
            "calc_date": "2026-04-02",
            "window_days": 45,
            "correlation": -0.6382,
            "covariance": -0.1294,
            "beta": 0.7421,
            "correlation_trend": "down",
            "correlation_ma": -0.6011,
            "alert": "correlation weakening",
            "alert_type": "correlation_breakdown",
        },
    ) as mock_calc:
        response = authenticated_client.post(
            "/api/hedge/actions/calculate_correlation/",
            {"asset1": "510300", "asset2": "511260", "window_days": 45},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset1"] == "510300"
    assert payload["asset2"] == "511260"
    assert payload["window_days"] == 45
    assert payload["correlation"] == -0.6382
    assert payload["beta"] == 0.7421
    assert payload["alert_type"] == "correlation_breakdown"
    mock_calc.assert_called_once_with(asset1="510300", asset2="511260", window_days=45)
