from types import SimpleNamespace
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
        username="filter_user",
        password="testpass123",
        email="filter@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_filter_get_data_returns_not_found_payload_when_no_series(authenticated_client):
    response_dto = SimpleNamespace(
        success=False,
        error="No saved filter data",
    )

    with patch("apps.filter.interface.api_views.GetFilterDataUseCase.execute", return_value=response_dto):
        response = authenticated_client.post(
            "/api/filter/get-data/",
            {"indicator_code": "PMI", "filter_type": "HP"},
            format="json",
        )

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "error": "No saved filter data",
    }


@pytest.mark.django_db
def test_filter_compare_returns_500_when_use_case_fails(authenticated_client):
    response_dto = SimpleNamespace(
        success=False,
        error="comparison failed",
    )

    with patch("apps.filter.interface.api_views.CompareFiltersUseCase.execute", return_value=response_dto):
        response = authenticated_client.post(
            "/api/filter/compare/",
            {"indicator_code": "PMI", "limit": 120},
            format="json",
        )

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "error": "comparison failed",
    }


@pytest.mark.django_db
def test_filter_config_endpoint_injects_indicator_code(authenticated_client):
    with patch(
        "apps.filter.interface.api_views.DjangoFilterRepository.get_filter_config",
        return_value={
            "hp_enabled": True,
            "hp_lambda": 129600.0,
            "kalman_enabled": True,
            "kalman_level_variance": 0.1,
            "kalman_slope_variance": 0.01,
            "kalman_observation_variance": 1.0,
        },
    ) as mock_config:
        response = authenticated_client.get("/api/filter/config/PMI/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["config"]["indicator_code"] == "PMI"
    assert payload["config"]["hp_lambda"] == 129600.0
    mock_config.assert_called_once_with("PMI")
