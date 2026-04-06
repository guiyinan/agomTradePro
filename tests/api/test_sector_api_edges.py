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
        username="sector_user",
        password="testpass123",
        email="sector@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_sector_analyze_maps_unavailable_result_to_200(authenticated_client):
    result = SimpleNamespace(
        success=False,
        status="unavailable",
        regime="Recovery",
        analysis_date="2026-04-02",
        top_sectors=[],
        market_breadth=None,
        concentration_score=None,
        error="upstream unavailable",
    )

    with patch("apps.sector.interface.views.AnalyzeSectorRotationUseCase.execute", return_value=result):
        response = authenticated_client.post(
            "/api/sector/analyze/",
            {"lookback_days": 20, "level": "SW1", "top_n": 5},
            format="json",
        )

    assert response.status_code == 200
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_sector_update_data_returns_400_on_failed_use_case(authenticated_client):
    result = SimpleNamespace(success=False, updated_count=0, error="adapter failed")

    with patch("apps.sector.interface.views.UpdateSectorDataUseCase.execute", return_value=result):
        response = authenticated_client.post(
            "/api/sector/update-data/",
            {"level": "SW1", "force_update": True},
            format="json",
        )

    assert response.status_code == 400
    assert response.json() == {"success": False, "error": "adapter failed"}


@pytest.mark.django_db
def test_sector_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/sector/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["endpoints"]["rotation"] == "/api/sector/rotation/"
    assert payload["endpoints"]["analyze"] == "/api/sector/analyze/"


@pytest.mark.django_db
def test_sector_rotation_lazy_bootstraps_when_local_sector_data_is_empty(authenticated_client):
    first_result = SimpleNamespace(
        success=False,
        status="unavailable",
        regime="Recovery",
        analysis_date="2026-04-06",
        top_sectors=[],
        market_breadth=None,
        concentration_score=None,
        error="未找到级别为 SW1 的板块数据",
        warning_message="sector_data_unavailable",
    )
    second_result = SimpleNamespace(
        success=True,
        status="ok",
        regime="Recovery",
        analysis_date="2026-04-06",
        top_sectors=[],
        market_breadth=None,
        concentration_score=None,
        error="",
    )
    sync_result = SimpleNamespace(success=True, updated_count=42, error="")

    with patch(
        "apps.sector.interface.views.AnalyzeSectorRotationUseCase.execute",
        side_effect=[first_result, second_result],
    ) as analyze_execute, patch(
        "apps.sector.interface.views.UpdateSectorDataUseCase.execute",
        return_value=sync_result,
    ) as sync_execute:
        response = authenticated_client.get("/api/sector/rotation/?level=SW1")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert analyze_execute.call_count == 2
    sync_execute.assert_called_once()

