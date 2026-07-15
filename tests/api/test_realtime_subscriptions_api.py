"""API contracts for durable realtime price subscriptions."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.realtime.infrastructure.models import PriceSubscriptionModel


@pytest.fixture
def subscription_users(db):
    user_model = get_user_model()
    return (
        user_model.objects.create_user(username="subscription-owner"),
        user_model.objects.create_user(username="subscription-other", is_staff=True),
    )


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_subscription_api_requires_authentication() -> None:
    assert _client().get("/api/realtime/subscriptions/").status_code == 401


@pytest.mark.django_db
def test_subscription_api_is_idempotent_owner_scoped_and_deletable(
    subscription_users,
) -> None:
    owner, other = subscription_users
    client = _client(owner)

    first = client.post(
        "/api/realtime/subscriptions/",
        {"asset_code": " 510300.sh "},
        format="json",
    )
    duplicate = client.post(
        "/api/realtime/subscriptions/",
        {"asset_code": "510300.SH"},
        format="json",
    )
    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.data["id"] == first.data["id"]
    assert PriceSubscriptionModel.objects.filter(owner=owner).count() == 1

    PriceSubscriptionModel.objects.create(owner=other, asset_code="000001.SZ")
    listed = client.get("/api/realtime/subscriptions/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1
    assert listed.data["results"][0]["asset_code"] == "510300.SH"

    assert client.delete(
        "/api/realtime/subscriptions/510300.sh/"
    ).status_code == 204
    assert client.delete(
        "/api/realtime/subscriptions/510300.sh/"
    ).status_code == 404
    assert PriceSubscriptionModel.objects.get(owner=other).is_active is True


@pytest.mark.django_db
def test_subscription_api_enforces_one_hundred_active_assets(subscription_users) -> None:
    owner, _ = subscription_users
    PriceSubscriptionModel.objects.bulk_create(
        [
            PriceSubscriptionModel(owner=owner, asset_code=f"ASSET{i:03d}")
            for i in range(100)
        ]
    )
    client = _client(owner)

    conflict = client.post(
        "/api/realtime/subscriptions/",
        {"asset_code": "OVERFLOW"},
        format="json",
    )
    duplicate = client.post(
        "/api/realtime/subscriptions/",
        {"asset_code": "ASSET000"},
        format="json",
    )

    assert conflict.status_code == 409
    assert duplicate.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [{}, {"asset_code": ""}, {"asset_code": "A" * 33}, {"asset_code": "A", "x": 1}],
)
def test_subscription_api_rejects_invalid_and_unknown_fields(
    subscription_users,
    payload,
) -> None:
    owner, _ = subscription_users
    response = _client(owner).post(
        "/api/realtime/subscriptions/",
        payload,
        format="json",
    )

    assert response.status_code == 400
