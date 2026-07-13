import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.audit.infrastructure.models import IndicatorThresholdConfigModel


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user(
        username="audit-threshold-staff",
        password="testpass123",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def regular_client(db):
    user = User.objects.create_user(
        username="audit-threshold-regular",
        password="testpass123",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _create_threshold_config():
    return IndicatorThresholdConfigModel._default_manager.create(
        indicator_code="CN_PMI",
        indicator_name="PMI",
        level_low=48.0,
        level_high=52.0,
        is_active=True,
    )


@pytest.mark.django_db
def test_threshold_update_preview_is_staff_only_and_read_only(staff_client, regular_client):
    config = _create_threshold_config()
    payload = {"indicator_code": "CN_PMI", "level_low": 49.0, "level_high": 51.0}

    denied = regular_client.post("/api/audit/update-threshold/preview/", payload, format="json")
    response = staff_client.post("/api/audit/update-threshold/preview/", payload, format="json")

    assert denied.status_code == 403
    assert response.status_code == 200
    assert response.json()["preview"] == {
        "indicator_code": "CN_PMI",
        "indicator_name": "PMI",
        "current": {"level_low": 48.0, "level_high": 52.0},
        "target": {"level_low": 49.0, "level_high": 51.0},
        "changed_fields": ["level_low", "level_high"],
        "writes": ["audit_indicator_threshold_config"],
    }
    config.refresh_from_db()
    assert (config.level_low, config.level_high) == (48.0, 52.0)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"indicator_code": "CN_PMI", "level_low": 51.0, "level_high": 51.0},
        {"indicator_code": "CN_PMI", "level_low": 52.0, "level_high": 51.0},
        {
            "indicator_code": "CN_PMI",
            "level_low": 49.0,
            "level_high": 51.0,
            "unknown": True,
        },
    ],
)
def test_threshold_update_rejects_invalid_contract(staff_client, payload):
    _create_threshold_config()

    response = staff_client.post("/api/audit/update-threshold/", payload, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_threshold_update_rejects_missing_and_unchanged_configs(staff_client):
    _create_threshold_config()

    missing = staff_client.post(
        "/api/audit/update-threshold/preview/",
        {"indicator_code": "MISSING", "level_low": 49.0, "level_high": 51.0},
        format="json",
    )
    unchanged = staff_client.post(
        "/api/audit/update-threshold/",
        {"indicator_code": "CN_PMI", "level_low": 48.0, "level_high": 52.0},
        format="json",
    )

    assert missing.status_code == 404
    assert unchanged.status_code == 400


@pytest.mark.django_db
def test_threshold_update_commits_exact_canonical_levels(staff_client):
    config = _create_threshold_config()

    response = staff_client.post(
        "/api/audit/update-threshold/",
        {"indicator_code": "CN_PMI", "level_low": 49.0, "level_high": 51.0},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["updated"]["changed_fields"] == ["level_low", "level_high"]
    config.refresh_from_db()
    assert (config.level_low, config.level_high) == (49.0, 51.0)
