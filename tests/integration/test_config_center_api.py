import pytest
from django.contrib.auth.models import User
from django.test import Client


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user(username="config_staff", password="pass1234", is_staff=True)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def normal_client(db):
    user = User.objects.create_user(username="config_normal", password="pass1234", is_staff=False)
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_config_center_snapshot_requires_staff(normal_client):
    response = normal_client.get("/api/system/config-center/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_config_center_snapshot_returns_sections(staff_client):
    response = staff_client.get("/api/system/config-center/")
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    assert "sections" in payload["data"]
    item_keys = {
        item["key"]
        for section in payload["data"]["sections"]
        for item in section["items"]
    }
    assert "agent_runtime_operator" in item_keys
    assert "valuation_repair" in item_keys
    assert "beta_gate" in item_keys
    assert "system_settings" in item_keys


@pytest.mark.django_db
def test_config_capabilities_returns_known_entries(staff_client):
    response = staff_client.get("/api/system/config-capabilities/")
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    keys = {item["key"] for item in payload["data"]}
    assert "agent_runtime_operator" in keys
    assert "valuation_repair" in keys
    assert "trading_cost" in keys
