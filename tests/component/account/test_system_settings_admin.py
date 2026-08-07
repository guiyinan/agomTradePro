import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.mark.django_db
def test_legacy_system_settings_admin_route_remains_retired() -> None:
    admin_user = get_user_model().objects.create_user(
        username=f"settings_admin_{uuid.uuid4().hex[:8]}",
        password="test-pass-123",
        is_staff=True,
        is_superuser=True,
    )
    client = Client()
    client.force_login(admin_user)

    response = client.get("/admin/config_center/systemsettingsmodel/")

    assert response.status_code == 404
