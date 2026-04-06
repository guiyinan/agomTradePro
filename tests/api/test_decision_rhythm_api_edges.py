import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="decision_rhythm_api_user",
        password="testpass123",
        email="decision-rhythm@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_decision_rhythm_submit_rejects_invalid_quota_period(authenticated_client):
    response = authenticated_client.post(
        "/api/decision-rhythm/submit/",
        {
            "asset_code": "000001.SH",
            "asset_class": "equity",
            "direction": "BUY",
            "quota_period": "YEARLY",
        },
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "quota_period" in str(payload["error"]).lower()


@pytest.mark.django_db
def test_decision_rhythm_precheck_requires_candidate_id(authenticated_client):
    response = authenticated_client.post(
        "/api/decision-workflow/precheck/",
        {},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_decision_rhythm_reset_quota_rejects_invalid_period(authenticated_client):
    response = authenticated_client.post(
        "/api/decision-rhythm/reset-quota/",
        {"period": "YEARLY"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_decision_workspace_recommendations_reject_invalid_page(authenticated_client, settings):
    settings.DECISION_WORKSPACE_V2_ENABLED = True

    response = authenticated_client.get(
        "/api/decision/workspace/recommendations/?account_id=default&page=bad"
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "page" in payload["error"]


@pytest.mark.django_db
def test_decision_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/decision/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["endpoints"]["workspace_recommendations"] == "/api/decision/workspace/recommendations/"
    assert payload["endpoints"]["execute_preview"] == "/api/decision/execute/preview/"
