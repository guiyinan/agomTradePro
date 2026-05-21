import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.account.infrastructure.models import MacroSizingConfigModel


@pytest.fixture
def macro_sizing_config(db):
    return MacroSizingConfigModel.objects.create(
        regime_tiers_json=[
            {"min_confidence": 0.6, "factor": 1.0},
            {"min_confidence": 0.4, "factor": 0.8},
            {"min_confidence": 0.0, "factor": 0.5},
        ],
        pulse_tiers_json=[
            {"min_composite": 0.3, "max_composite": 99, "factor": 1.0},
            {"min_composite": -0.3, "max_composite": 0.3, "factor": 0.85},
            {"min_composite": -99, "max_composite": -0.3, "factor": 0.7},
        ],
        warning_factor=0.5,
        drawdown_tiers_json=[
            {"min_drawdown": 0.15, "factor": 0.0},
            {"min_drawdown": 0.1, "factor": 0.5},
            {"min_drawdown": 0.05, "factor": 0.8},
            {"min_drawdown": 0.0, "factor": 1.0},
        ],
        market_temperature_cold_factor=1.0,
        market_temperature_warm_factor=1.0,
        market_temperature_hot_factor=0.9,
        market_temperature_overheat_factor=0.75,
        market_temperature_extreme_factor=0.35,
        block_new_position_on_extreme=True,
        version=1,
        is_active=True,
        description="seed",
    )


@pytest.fixture
def user_client(db):
    user = User.objects.create_user(username="macro_config_user", password="pass1234")
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user(
        username="macro_config_staff",
        password="pass1234",
        is_staff=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_macro_sizing_config_get_returns_active_payload(user_client, macro_sizing_config):
    response = user_client.get("/api/account/macro-sizing-config/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 1
    assert payload["market_temperature_hot_factor"] == 0.9
    assert payload["market_temperature_extreme_factor"] == 0.35
    assert payload["block_new_position_on_extreme"] is True


@pytest.mark.django_db
def test_macro_sizing_config_patch_requires_staff(user_client, macro_sizing_config):
    response = user_client.patch(
        "/api/account/macro-sizing-config/",
        data={"market_temperature_hot_factor": 0.8},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_macro_sizing_config_patch_creates_new_active_version(staff_client, macro_sizing_config):
    response = staff_client.patch(
        "/api/account/macro-sizing-config/",
        data={
            "market_temperature_hot_factor": 0.82,
            "market_temperature_overheat_factor": 0.68,
            "description": "sdk update",
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 2
    assert payload["market_temperature_hot_factor"] == 0.82
    assert payload["market_temperature_overheat_factor"] == 0.68
    assert payload["description"] == "sdk update"
    assert MacroSizingConfigModel.objects.filter(is_active=True).count() == 1

    latest = MacroSizingConfigModel.objects.get(version=2)
    assert latest.is_active is True
    assert MacroSizingConfigModel.objects.filter(version=1, is_active=False).exists()
    assert latest.market_temperature_extreme_factor == 0.35
