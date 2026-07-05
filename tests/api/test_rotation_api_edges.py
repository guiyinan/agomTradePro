from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.rotation.infrastructure.models import RotationConfigModel, RotationSignalModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="rotation_user",
        password="testpass123",
        email="rotation@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_rotation_api_root_contract(api_client):
    response = api_client.get("/api/rotation/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["assets"] == "/api/rotation/assets/"
    assert payload["endpoints"]["actions"] == "/api/rotation/"


@pytest.mark.django_db
def test_rotation_compare_requires_asset_codes(authenticated_client):
    response = authenticated_client.post("/api/rotation/compare/", {}, format="json")

    assert response.status_code == 400
    assert response.json()["error"] == "asset_codes is required"


@pytest.mark.django_db
def test_rotation_generate_signal_returns_404_when_service_returns_none(authenticated_client):
    with patch(
        "apps.rotation.application.interface_services.RotationIntegrationService.generate_rotation_signal",
        return_value=None,
    ):
        response = authenticated_client.post(
            "/api/rotation/generate-signal/",
            {"config_name": "missing-config"},
            format="json",
        )

    assert response.status_code == 404
    assert "missing-config" in response.json()["error"]


@pytest.mark.django_db
def test_rotation_clear_cache_calls_service(authenticated_client):
    with patch(
        "apps.rotation.application.interface_services.RotationIntegrationService.clear_price_cache"
    ) as mock_clear:
        response = authenticated_client.post("/api/rotation/clear-cache/", {}, format="json")

    assert response.status_code == 200
    assert response.json() == {"status": "cache cleared"}
    mock_clear.assert_called_once_with()


@pytest.mark.django_db
def test_rotation_latest_signal_exposes_quality_metadata(authenticated_client):
    config = RotationConfigModel.objects.create(
        name="质量测试轮动",
        strategy_type="momentum",
        asset_universe=["510300", "510500", "159915"],
        top_n=2,
        is_active=True,
    )
    RotationSignalModel.objects.create(
        config=config,
        signal_date="2026-07-04",
        target_allocation={"510300": 1.0},
        momentum_ranking=[["510300", 0.12]],
        expected_return=0.0,
        expected_volatility=0.0,
        action_required="rebalance",
        reason="partial coverage",
    )

    response = authenticated_client.get("/api/rotation/signals/latest/")

    assert response.status_code == 200
    payload = response.json()
    row = next(item for item in payload if item["config_name"] == "质量测试轮动")
    assert row["data_quality"]["status"] == "degraded"
    assert row["data_quality"]["coverage_ratio"] == pytest.approx(1 / 3, abs=0.0001)
    assert row["data_quality"]["metrics_available"] is False
    assert "partial_price_coverage" in row["data_quality"]["warnings"]
    assert "risk_return_metrics_unavailable" in row["data_quality"]["warnings"]
    assert "is_stale" in row
    assert "staleness_days" in row
    assert row["action_required"] == "rebalance"
    assert row["actionable"] is False
    assert row["execution_block_reason"] in {
        "stale_rotation_signal",
        "rotation_data_quality_degraded",
    }
