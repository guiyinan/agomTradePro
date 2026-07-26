from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.filter.interface.serializers import (
    ApplyFilterRequestSerializer,
    CompareFiltersRequestSerializer,
    GetFilterDataRequestSerializer,
    UpdateFilterConfigRequestSerializer,
)


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
        error_code="FILTER_RESULT_NOT_FOUND",
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
        "error": "No saved filter data.",
        "error_code": "FILTER_RESULT_NOT_FOUND",
    }


@pytest.mark.django_db
def test_filter_compare_returns_500_when_use_case_fails(authenticated_client):
    response_dto = SimpleNamespace(
        success=False,
        error="secret comparison detail",
        error_code="FILTER_COMPARISON_FAILED",
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
        "error": "Filter comparison failed.",
        "error_code": "FILTER_COMPARISON_FAILED",
    }


@pytest.mark.django_db
def test_filter_apply_endpoint_allows_side_effect_free_calculation(authenticated_client):
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
            {
                "indicator_code": "PMI",
                "filter_type": "HP",
                "limit": 120,
                "save_results": False,
            },
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
    assert request_dto.save_results is False


@pytest.mark.django_db
def test_filter_apply_rejects_persistence_for_ordinary_user(authenticated_client):
    with patch(
        "apps.filter.interface.api_views.ApplyFilterUseCase.execute",
        autospec=True,
    ) as mock_execute:
        response = authenticated_client.post(
            "/api/filter/",
            {"indicator_code": "PMI", "filter_type": "HP"},
            format="json",
        )

    assert response.status_code == 403
    assert response.json() == {
        "success": False,
        "error": "Administrator access is required to persist filter results.",
    }
    mock_execute.assert_not_called()


@pytest.mark.django_db
def test_filter_apply_rejects_unknown_fields_before_execution(authenticated_client):
    with patch(
        "apps.filter.interface.api_views.ApplyFilterUseCase.execute",
        autospec=True,
    ) as mock_execute:
        response = authenticated_client.post(
            "/api/filter/",
            {
                "indicator_code": "PMI",
                "filter_type": "HP",
                "save_results": False,
                "lambda": 1600,
            },
            format="json",
        )

    assert response.status_code == 400
    assert "Unknown fields: lambda" in response.json()["error"]
    mock_execute.assert_not_called()


@pytest.mark.parametrize(
    "serializer_class",
    [
        ApplyFilterRequestSerializer,
        GetFilterDataRequestSerializer,
        CompareFiltersRequestSerializer,
    ],
)
def test_filter_request_serializers_reject_inverted_date_windows(serializer_class):
    payload = {
        "indicator_code": "PMI",
        "start_date": "2026-02-01",
        "end_date": "2026-01-01",
    }
    if serializer_class is not CompareFiltersRequestSerializer:
        payload["filter_type"] = "HP"
    serializer = serializer_class(data=payload)

    assert serializer.is_valid() is False
    assert "end_date" in serializer.errors


@pytest.mark.parametrize("limit", [0, 1001])
def test_filter_compare_serializer_rejects_unbounded_limit(limit):
    serializer = CompareFiltersRequestSerializer(data={"indicator_code": "PMI", "limit": limit})

    assert serializer.is_valid() is False
    assert "limit" in serializer.errors


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
def test_filter_config_patch_updates_by_indicator_code(authenticated_client, auth_user):
    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
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
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"unexpected": 1},
        {"hp_lambda": -1},
        {"kalman_level_variance": -0.1},
        {"kalman_observation_variance": 0},
    ],
)
def test_filter_config_patch_rejects_invalid_mutations_before_repository(
    authenticated_client,
    auth_user,
    payload,
):
    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    with patch(
        "apps.filter.interface.api_views.DjangoFilterRepository.update_filter_config"
    ) as mock_update:
        response = authenticated_client.patch(
            "/api/filter/config/PMI/",
            payload,
            format="json",
        )

    assert response.status_code == 400
    mock_update.assert_not_called()


@pytest.mark.django_db
def test_filter_config_rejects_overlong_indicator_before_repository(
    authenticated_client,
    auth_user,
):
    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    indicator_code = "X" * 51
    with patch(
        "apps.filter.interface.api_views.DjangoFilterRepository.update_filter_config"
    ) as mock_update:
        response = authenticated_client.patch(
            f"/api/filter/config/{indicator_code}/",
            {"hp_enabled": False},
            format="json",
        )

    assert response.status_code == 400
    assert "indicator_code" in response.json()["details"]
    mock_update.assert_not_called()


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("hp_lambda", float("nan")),
        ("hp_lambda", float("inf")),
        ("kalman_slope_variance", True),
    ],
)
def test_filter_config_serializer_rejects_non_finite_values(field_name, value):
    serializer = UpdateFilterConfigRequestSerializer(data={field_name: value})

    assert serializer.is_valid() is False
    assert field_name in serializer.errors


@pytest.mark.django_db
def test_filter_config_delete_returns_not_found_when_missing(authenticated_client, auth_user):
    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
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


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_filter_config_mutations_require_admin(
    authenticated_client,
    method,
):
    with (
        patch(
            "apps.filter.interface.api_views.DjangoFilterRepository.update_filter_config"
        ) as mock_update,
        patch(
            "apps.filter.interface.api_views.DjangoFilterRepository.delete_filter_config"
        ) as mock_delete,
    ):
        client_method = getattr(authenticated_client, method)
        response = client_method(
            "/api/filter/config/PMI/",
            {"hp_enabled": False} if method == "patch" else None,
            format="json",
        )

    assert response.status_code == 403
    mock_update.assert_not_called()
    mock_delete.assert_not_called()
