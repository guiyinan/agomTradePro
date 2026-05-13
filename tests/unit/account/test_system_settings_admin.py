import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.account.infrastructure.models import SystemSettingsModel


@pytest.mark.django_db
def test_system_settings_admin_singleton_entry_opens_change_form():
    admin_user = get_user_model().objects.create_user(
        username=f"settings_admin_{uuid.uuid4().hex[:8]}",
        password="test-pass-123",
        is_staff=True,
        is_superuser=True,
    )
    SystemSettingsModel.get_settings()

    client = Client()
    client.force_login(admin_user)

    response = client.get("/admin/config_center/systemsettingsmodel/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "系统配置" in content
    assert "name=\"backup_enabled\"" in content
    assert "TypeError at /admin/config_center/systemsettingsmodel/" not in content
