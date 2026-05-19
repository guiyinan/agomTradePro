"""Integration tests for market thermometer APIs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.data_center.infrastructure.models import (
    MarketThermometerSnapshotModel,
    MarketThermometerUserOverrideModel,
)


@pytest.fixture
def admin_client(db):
    user = User.objects.create_user(
        username="thermo-admin",
        password="pass1234",
        is_staff=True,
        is_superuser=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def user_client(db):
    user = User.objects.create_user(
        username="thermo-user",
        password="pass1234",
        is_staff=False,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_market_thermometer_current_returns_user_override_contract(user_client):
    user = User.objects.get(username="thermo-user")
    today = date.today()
    MarketThermometerSnapshotModel.objects.create(
        observed_at=today,
        score=78.0,
        band="overheat",
        change_5d=5.0,
        change_20d=14.0,
        components=[],
        trigger_reasons=["成交额抬升"],
        stale_components=[],
        missing_components=[],
        valid_component_count=5,
        data_source="calculated",
        must_not_use_for_decision=False,
        blocked_reason="",
        calculated_at=datetime.now(UTC),
    )
    MarketThermometerUserOverrideModel.objects.create(
        user=user,
        warm_threshold=30.0,
        hot_threshold=55.0,
        overheat_threshold=72.0,
        extreme_threshold=90.0,
    )

    response = user_client.get("/api/data-center/market-thermometer/current/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["score"] == 78.0
    assert payload["threshold_source"] == "user_override"
    assert payload["effective_band"] == "overheat"
    assert payload["thresholds"]["hot_threshold"] == 55.0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("put", "/api/data-center/market-thermometer/config/", {"hot_threshold": 62.0}),
        ("post", "/api/data-center/market-thermometer/calculate/", {}),
        ("post", "/api/data-center/market-thermometer/sync-inputs/", {}),
        ("post", "/api/data-center/market-thermometer/import/investor-accounts/", {"csv_text": "reporting_period,value\n2026-04-30,100\n"}),
    ],
)
def test_market_thermometer_admin_endpoints_forbid_regular_users(user_client, method, path, payload):
    response = getattr(user_client, method)(
        path,
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_market_thermometer_me_supports_upsert_and_delete(user_client):
    response = user_client.put(
        "/api/data-center/market-thermometer/me/",
        data=json.dumps(
            {
                "warm_threshold": 32.0,
                "hot_threshold": 57.0,
                "overheat_threshold": 74.0,
                "extreme_threshold": 92.0,
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "user_override"
    assert payload["effective"]["extreme_threshold"] == 92.0

    delete_response = user_client.delete("/api/data-center/market-thermometer/me/")

    assert delete_response.status_code == 204
    assert MarketThermometerUserOverrideModel.objects.count() == 0
