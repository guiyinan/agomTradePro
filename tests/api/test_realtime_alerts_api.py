"""API contracts for owner-scoped realtime alerts."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.realtime.infrastructure.models import PriceAlertModel


@pytest.fixture
def users(db):
    user_model = get_user_model()
    return (
        user_model.objects.create_user(username="alert-owner"),
        user_model.objects.create_user(username="alert-other", is_staff=True),
    )


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_alert_api_requires_authentication() -> None:
    response = _client().get("/api/realtime/alerts/")

    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_alert_api_create_list_get_update_activate_and_delete(users) -> None:
    owner, _ = users
    client = _client(owner)

    created = client.post(
        "/api/realtime/alerts/",
        {
            "asset_code": " 510300.sh ",
            "condition": "cross_up",
            "threshold": "3.500001",
            "message": "突破提醒",
        },
        format="json",
    )
    assert created.status_code == 201
    assert created["Content-Type"].startswith("application/json")
    assert created.data["asset_code"] == "510300.SH"
    assert created.data["threshold"] == "3.500001"
    alert_id = created.data["id"]

    listed = client.get("/api/realtime/alerts/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1
    assert listed.data["results"][0]["id"] == alert_id

    detail = client.get(f"/api/realtime/alerts/{alert_id}/")
    assert detail.status_code == 200

    PriceAlertModel.objects.filter(id=alert_id).update(
        status="triggered",
        triggered_price=Decimal("3.6"),
    )
    updated = client.patch(
        f"/api/realtime/alerts/{alert_id}/",
        {
            "condition": "below",
            "threshold": "3.100000",
            "message": "跌破提醒",
            "status": "active",
        },
        format="json",
    )
    assert updated.status_code == 200
    assert updated.data["condition"] == "below"
    assert updated.data["status"] == "active"
    assert updated.data["triggered_price"] is None
    assert updated.data["triggered_at"] is None

    deleted = client.delete(f"/api/realtime/alerts/{alert_id}/")
    assert deleted.status_code == 204
    assert client.get(f"/api/realtime/alerts/{alert_id}/").status_code == 404


@pytest.mark.django_db
def test_alert_api_owner_scope_also_applies_to_staff(users) -> None:
    owner, staff = users
    record = PriceAlertModel.objects.create(
        owner=owner,
        asset_code="510300.SH",
        condition="above",
        threshold=Decimal("3"),
    )
    staff_client = _client(staff)

    assert staff_client.get(f"/api/realtime/alerts/{record.id}/").status_code == 404
    assert staff_client.patch(
        f"/api/realtime/alerts/{record.id}/",
        {"message": "hijack"},
        format="json",
    ).status_code == 404
    assert staff_client.delete(f"/api/realtime/alerts/{record.id}/").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"asset_code": "510300.SH", "condition": "above", "threshold": "0"},
        {"asset_code": "", "condition": "above", "threshold": "3"},
        {"asset_code": "A" * 33, "condition": "above", "threshold": "3"},
        {"asset_code": "510300.SH", "condition": "invalid", "threshold": "3"},
        {
            "asset_code": "510300.SH",
            "condition": "above",
            "threshold": "3",
            "message": "x" * 501,
        },
        {
            "asset_code": "510300.SH",
            "condition": "above",
            "threshold": "3",
            "unexpected": True,
        },
    ],
)
def test_alert_api_rejects_invalid_or_unknown_fields(users, payload) -> None:
    owner, _ = users
    response = _client(owner).post("/api/realtime/alerts/", payload, format="json")

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_alert_update_rejects_empty_and_immutable_fields(users) -> None:
    owner, _ = users
    client = _client(owner)
    created = client.post(
        "/api/realtime/alerts/",
        {"asset_code": "510300.SH", "condition": "above", "threshold": "3"},
        format="json",
    )
    alert_id = created.data["id"]

    assert client.patch(
        f"/api/realtime/alerts/{alert_id}/", {}, format="json"
    ).status_code == 400
    assert client.patch(
        f"/api/realtime/alerts/{alert_id}/",
        {"asset_code": "000001.SZ"},
        format="json",
    ).status_code == 400
