import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.account.infrastructure.models import AccountProfileModel


def _ensure_account_profile(user: User) -> None:
    AccountProfileModel.objects.get_or_create(
        user=user,
        defaults={
            "display_name": user.username,
            "risk_tolerance": "moderate",
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
        },
    )


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user(username="config_staff", password="pass1234", is_staff=True)
    _ensure_account_profile(user)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def normal_client(db):
    user = User.objects.create_user(username="config_normal", password="pass1234", is_staff=False)
    _ensure_account_profile(user)
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
    assert "account_settings" in item_keys
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


@pytest.mark.django_db
def test_config_center_snapshot_includes_market_data_provider_summary(staff_client, monkeypatch):
    monkeypatch.setattr(
        "apps.market_data.interface.page_views.build_provider_dashboard",
        lambda: {
            "provider_count": 2,
            "healthy_provider_count": 1,
            "unhealthy_provider_count": 1,
            "providers": [
                {"name": "eastmoney", "healthy": False},
                {"name": "tushare", "healthy": True},
            ],
        },
    )

    response = staff_client.get("/api/system/config-center/")

    assert response.status_code == 200
    items = {
        item["key"]: item
        for section in response.json()["data"]["sections"]
        for item in section["items"]
    }
    market_data_item = items["market_data_providers"]
    assert market_data_item["status"] == "attention"
    assert market_data_item["summary"]["provider_count"] == 2
    assert market_data_item["summary"]["healthy_provider_count"] == 1


@pytest.mark.django_db
def test_ops_center_page_is_single_entry_for_normal_user(normal_client):
    response = normal_client.get("/settings/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "设置中心" in content
    assert "统一入口" in content
    assert "账户设置" in content


@pytest.mark.django_db
def test_ops_center_page_shows_system_settings_for_staff(staff_client):
    response = staff_client.get("/settings/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "设置中心" in content
    assert "系统设置" in content
