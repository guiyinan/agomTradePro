"""
E2E-style checks for audit admin console (Django client based).
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.mark.django_db
class TestAuditAdminConsole:
    @pytest.fixture(autouse=True)
    def _override_cache_and_throttle(self, settings):
        settings.CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "audit-admin-e2e",
            }
        }
        settings.REST_FRAMEWORK = {
            **getattr(settings, "REST_FRAMEWORK", {}),
            "DEFAULT_THROTTLE_CLASSES": [],
            "DEFAULT_THROTTLE_RATES": {},
        }

    def test_admin_can_open_admin_page(self):
        user_model = get_user_model()
        admin = user_model.objects.create_user(
            username=f"admin_{uuid.uuid4().hex[:8]}",
            password="test-pass-123",
            is_superuser=True,
        )

        client = Client()
        client.force_login(admin)

        response = client.get("/audit/operation-logs/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "操作审计日志" in content

    def test_regular_user_gets_403_on_admin_page(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username=f"user_{uuid.uuid4().hex[:8]}",
            password="test-pass-123",
        )
        user.rbac_role = "analyst"

        client = Client()
        client.force_login(user)

        response = client.get("/audit/operation-logs/")
        assert response.status_code == 403
