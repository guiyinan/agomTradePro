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
