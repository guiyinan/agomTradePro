import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from apps.policy.interface.admin import (
    PolicyLogAdmin,
    RSSSourceConfigAdmin,
    _require_admin_user_id,
)


def test_policy_admin_metadata_uses_supported_django_decorators() -> None:
    """Display columns and actions should expose official Django metadata."""

    assert PolicyLogAdmin.level_badge.short_description == "档位"
    assert PolicyLogAdmin.level_badge.admin_order_field == "level"
    assert PolicyLogAdmin.approve_selected.short_description == "✅ 批量通过选中项"
    assert RSSSourceConfigAdmin.test_fetch.short_description == "🔄 测试抓取选中源"


def test_policy_admin_action_rejects_anonymous_user() -> None:
    """Audit actions must not persist an anonymous reviewer."""

    request = RequestFactory().post("/admin/policy/policylog/")
    request.user = AnonymousUser()

    with pytest.raises(PermissionDenied, match="persisted admin user"):
        _require_admin_user_id(request)


@pytest.mark.django_db
def test_policy_admin_changelist_loads(client, django_user_model) -> None:
    """Typed ModelAdmin bases must remain loadable by Django at runtime."""

    user = django_user_model.objects.create_superuser(
        username="policy-admin",
        email="policy-admin@example.com",
        password="test-password",
    )
    client.force_login(user)

    response = client.get("/admin/policy/policylog/")

    assert response.status_code == 200
