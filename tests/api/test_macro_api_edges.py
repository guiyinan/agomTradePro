import json
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.macro.infrastructure.models import MacroIndicator


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="macro_user",
        password="testpass123",
        email="macro@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_macro_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/macro/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["fetch"] == "/api/macro/fetch/"
    assert payload["endpoints"]["table"] == "/api/macro/table/"


@pytest.mark.django_db
def test_macro_fetch_rejects_invalid_json_body(authenticated_client):
    response = authenticated_client.post(
        "/api/macro/fetch/",
        data="{bad json",
        content_type="application/json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "无效的请求数据" in payload["message"]


@pytest.mark.django_db
def test_macro_supported_indicators_contract(authenticated_client):
    response = authenticated_client.get("/api/macro/supported-indicators/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert isinstance(payload["indicators"], list)
    assert payload["count"] == len(payload["indicators"])


@pytest.mark.django_db
def test_macro_indicator_data_requires_code(authenticated_client):
    response = authenticated_client.get("/api/macro/indicator-data/")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["message"] == "请指定指标代码"


@pytest.mark.django_db
def test_macro_indicator_data_accepts_indicator_alias(authenticated_client):
    response = authenticated_client.get("/api/macro/indicator-data/?indicator=CN_PMI")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True


@pytest.mark.django_db
def test_macro_legacy_datasource_routes_are_removed(authenticated_client):
    response = authenticated_client.get("/api/macro/datasources/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_macro_delete_rejects_invalid_json_body(authenticated_client):
    response = authenticated_client.post(
        "/api/macro/delete/",
        data=json.dumps({"indicator_code": "CN_PMI", "start_date": "bad-date"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "无效的请求数据" in payload["message"]


@pytest.mark.django_db
def test_macro_record_crud_and_table_flow(authenticated_client):
    create_response = authenticated_client.post(
        "/api/macro/record/create/",
        data=json.dumps(
            {
                "code": "CN_TEST_MACRO",
                "value": 51.2,
                "reporting_period": "2026-03-01",
                "period_type": "M",
                "published_at": "2026-03-05",
                "source": "manual",
                "revision_number": 1,
            }
        ),
        content_type="application/json",
    )

    assert create_response.status_code == 200
    created_payload = create_response.json()
    assert created_payload["success"] is True
    record_id = created_payload["data"]["id"]

    table_response = authenticated_client.get("/api/macro/table/?code=CN_TEST_MACRO")
    assert table_response.status_code == 200
    table_payload = table_response.json()
    assert table_payload["success"] is True
    assert table_payload["total"] == 1
    assert table_payload["data"][0]["id"] == record_id

    update_response = authenticated_client.put(
        f"/api/macro/record/{record_id}/update/",
        data=json.dumps(
            {
                "value": 52.8,
                "source": "manual-updated",
                "published_at": None,
            }
        ),
        content_type="application/json",
    )
    assert update_response.status_code == 200
    updated_payload = update_response.json()
    assert updated_payload["success"] is True
    assert updated_payload["data"]["storage_value"] == 52.8
    assert updated_payload["data"]["source"] == "manual-updated"
    assert updated_payload["data"]["published_at"] is None

    delete_response = authenticated_client.delete(f"/api/macro/record/{record_id}/")
    assert delete_response.status_code == 200
    assert delete_response.json()["success"] is True
    assert not MacroIndicator.objects.filter(id=record_id).exists()


@pytest.mark.django_db
def test_macro_batch_delete_removes_selected_rows(authenticated_client):
    first = MacroIndicator.objects.create(
        code="CN_BATCH_A",
        value=1.0,
        unit="指数",
        original_unit="指数",
        reporting_period=date(2026, 3, 1),
        period_type="M",
        source="manual",
        revision_number=1,
    )
    second = MacroIndicator.objects.create(
        code="CN_BATCH_B",
        value=2.0,
        unit="指数",
        original_unit="指数",
        reporting_period=date(2026, 3, 1),
        period_type="M",
        source="manual",
        revision_number=1,
    )

    response = authenticated_client.post(
        "/api/macro/batch-delete/",
        data=json.dumps({"ids": [first.id, second.id]}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["deleted_count"] == 2
    assert MacroIndicator.objects.filter(id__in=[first.id, second.id]).count() == 0
