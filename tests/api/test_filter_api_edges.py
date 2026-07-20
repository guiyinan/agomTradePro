from datetime import date
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
def test_filter_health_success_contract(authenticated_client):
    response = authenticated_client.get("/api/filter/health/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response["Deprecation"] == "true"
    assert response["Sunset"] == "Wed, 30 Sep 2026 00:00:00 GMT"
    assert response["X-Agom-Deprecated-Since"] == "0.8.0"
    assert "do not add new Filter API" in response["X-Agom-Deprecation-Notice"]
    assert response.json() == {
        "status": "healthy",
        "service": "Filter API",
        "filters_available": ["HP", "Kalman"],
    }


@pytest.mark.django_db
def test_filter_get_data_returns_not_found_payload_when_no_series(authenticated_client):
    response_dto = SimpleNamespace(
        success=False,
        error="No saved filter data",
    )

    with patch(
        "apps.filter.interface.api_views.GetFilterDataUseCase.execute", return_value=response_dto
    ):
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

    with patch(
        "apps.filter.interface.api_views.CompareFiltersUseCase.execute", return_value=response_dto
    ):
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
def test_filter_apply_endpoint_defaults_save_results_and_returns_series(authenticated_client):
    response_dto = SimpleNamespace(
        success=True,
        series=SimpleNamespace(
            indicator_code="PMI",
            filter_type=SimpleNamespace(value="HP"),
            params={"lamb": 129600.0},
            results=[
                SimpleNamespace(
                    date=date(2026, 1, 1),
                    original_value=50.1,
                    filtered_value=49.9,
                    slope=None,
                ),
                SimpleNamespace(
                    date=date(2026, 2, 1),
                    original_value=50.4,
                    filtered_value=50.0,
                    slope=None,
                ),
            ],
            calculated_at=date(2026, 2, 1),
        ),
        warnings=[],
        error=None,
    )

    with patch(
        "apps.filter.interface.api_views.ApplyFilterUseCase.execute",
        autospec=True,
        return_value=response_dto,
    ) as mock_execute:
        response = authenticated_client.post(
            "/api/filter/",
            {"indicator_code": "PMI", "filter_type": "HP", "limit": 120},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["series"]["indicator_code"] == "PMI"
    assert payload["series"]["filter_type"] == "HP"
    assert payload["series"]["dates"] == ["2026-01-01", "2026-02-01"]

    request_dto = mock_execute.call_args.args[1]
    assert request_dto.indicator_code == "PMI"
    assert request_dto.limit == 120
    assert request_dto.save_results is True


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


@pytest.mark.django_db
def test_filter_indicators_endpoint_success_contract(authenticated_client):
    repository = SimpleNamespace(
        get_available_indicators=lambda: [
            {"code": "PMI", "name": "PMI", "category": "macro"},
            {"code": "CPI", "name": "CPI", "category": "inflation"},
        ]
    )

    with patch(
        "apps.filter.interface.api_views.get_filter_repository",
        return_value=repository,
    ) as mock_repository:
        response = authenticated_client.get("/api/filter/indicators/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert len(payload["indicators"]) == 2
    assert payload["indicators"][0]["code"] == "PMI"
    assert payload["indicators"][1]["code"] == "CPI"
    mock_repository.assert_called_once_with()


@pytest.mark.django_db
def test_filter_config_patch_updates_by_indicator_code(authenticated_client):
    with patch(
        "apps.filter.interface.api_views.DjangoFilterRepository.update_filter_config",
        return_value={
            "indicator_code": "PMI",
            "hp_enabled": False,
            "hp_lambda": 6400.0,
            "kalman_enabled": True,
            "kalman_level_variance": 0.1,
            "kalman_slope_variance": 0.01,
            "kalman_observation_variance": 1.0,
            "description": "updated config",
        },
    ) as mock_update:
        response = authenticated_client.patch(
            "/api/filter/config/PMI/",
            {"hp_enabled": False, "hp_lambda": 6400.0, "description": "updated config"},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["config"]["indicator_code"] == "PMI"
    assert payload["config"]["hp_enabled"] is False
    assert payload["config"]["description"] == "updated config"
    mock_update.assert_called_once_with(
        "PMI",
        {
            "hp_enabled": False,
            "hp_lambda": 6400.0,
            "description": "updated config",
        },
    )


@pytest.mark.django_db
def test_filter_config_delete_returns_not_found_when_missing(authenticated_client):
    with patch(
        "apps.filter.interface.api_views.DjangoFilterRepository.delete_filter_config",
        return_value=False,
    ) as mock_delete:
        response = authenticated_client.delete("/api/filter/config/PMI/")

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "error": "Filter config not found: PMI",
    }
    mock_delete.assert_called_once_with("PMI")
