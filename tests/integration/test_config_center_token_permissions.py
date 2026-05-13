from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.account.infrastructure.models import AccountProfileModel, UserAccessTokenModel
from apps.config_center.infrastructure.models import SystemSettingsModel


def _create_profile(user: User) -> None:
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": user.username,
            "initial_capital": Decimal("1000000.00"),
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
            "mcp_enabled": True,
        },
    )


def _authorize(client: APIClient, raw_key: str) -> None:
    client.credentials(HTTP_AUTHORIZATION=f"Token {raw_key}")


@pytest.mark.django_db
def test_read_only_token_can_read_qlib_runtime(tmp_path):
    user = User.objects.create_user(
        username="config_staff_read_token",
        password="pass12345",
        is_staff=True,
    )
    _create_profile(user)
    _, raw_key = UserAccessTokenModel.create_token(
        user=user,
        name="staff-readonly",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    provider_dir = tmp_path / "qlib" / "cn_data"
    model_dir = tmp_path / "qlib" / "models"
    provider_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.qlib_provider_uri = str(provider_dir)
    settings_obj.qlib_model_path = str(model_dir)
    settings_obj.save(update_fields=["qlib_provider_uri", "qlib_model_path", "updated_at"])

    client = APIClient()
    _authorize(client, raw_key)
    response = client.get("/api/system/config-center/qlib/runtime/")

    assert response.status_code == 200
    assert response.json()["success"] is True


@pytest.mark.django_db
def test_read_only_token_cannot_write_qlib_runtime(tmp_path):
    user = User.objects.create_user(
        username="config_admin_readonly_token",
        password="pass12345",
        is_staff=True,
        is_superuser=True,
    )
    _create_profile(user)
    _, raw_key = UserAccessTokenModel.create_token(
        user=user,
        name="admin-readonly",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    provider_dir = tmp_path / "qlib" / "cn_data"
    model_dir = tmp_path / "qlib" / "models"
    provider_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)

    client = APIClient()
    _authorize(client, raw_key)
    response = client.post(
        "/api/system/config-center/qlib/runtime/",
        {
            "enabled": True,
            "provider_uri": str(provider_dir),
            "region": "CN",
            "model_root": str(model_dir),
        },
        format="json",
    )

    assert response.status_code == 403
    assert "read-only" in response.json()["error"]


@pytest.mark.django_db
def test_read_write_token_still_needs_superuser_for_qlib_runtime_write(tmp_path):
    user = User.objects.create_user(
        username="config_staff_write_token",
        password="pass12345",
        is_staff=True,
        is_superuser=False,
    )
    _create_profile(user)
    _, raw_key = UserAccessTokenModel.create_token(
        user=user,
        name="staff-write",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE,
    )

    provider_dir = tmp_path / "qlib" / "cn_data"
    model_dir = tmp_path / "qlib" / "models"
    provider_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)

    client = APIClient()
    _authorize(client, raw_key)
    response = client.post(
        "/api/system/config-center/qlib/runtime/",
        {
            "enabled": True,
            "provider_uri": str(provider_dir),
            "region": "CN",
            "model_root": str(model_dir),
        },
        format="json",
    )

    assert response.status_code == 403
    assert "superuser" in response.json()["detail"]
