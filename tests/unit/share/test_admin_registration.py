"""Share Admin discovery, confidentiality, and audit immutability regressions."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib import admin
from django.test import RequestFactory

from apps.share.interface.admin import (
    ShareAccessLogAdmin,
    ShareDisclaimerConfigAdmin,
    ShareLinkAdmin,
    ShareSnapshotAdmin,
)
from apps.share.models import (
    ShareAccessLogModel,
    ShareDisclaimerConfigModel,
    ShareLinkModel,
    ShareSnapshotModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


def test_share_models_are_registered_once_through_typed_admins() -> None:
    """Django autodiscovery exposes all Share governance models."""

    expected = {
        ShareLinkModel: ShareLinkAdmin,
        ShareSnapshotModel: ShareSnapshotAdmin,
        ShareAccessLogModel: ShareAccessLogAdmin,
        ShareDisclaimerConfigModel: ShareDisclaimerConfigAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)


@pytest.mark.django_db
def test_share_generated_records_and_link_deletion_are_blocked(django_user_model: type) -> None:
    """Admin cannot fabricate or erase share links, snapshots, or access evidence."""

    request = RequestFactory().get("/admin/share/")
    request.user = django_user_model.objects.create_superuser(
        username="share-root",
        email="share-root@example.com",
        password="test-password",
    )
    link_admin = admin.site._registry[ShareLinkModel]
    snapshot_admin = admin.site._registry[ShareSnapshotModel]
    access_admin = admin.site._registry[ShareAccessLogModel]

    assert link_admin.has_add_permission(request) is False
    assert link_admin.has_delete_permission(request) is False
    assert "password_hash" in link_admin.readonly_fields
    for generated_admin in (snapshot_admin, access_admin):
        assert generated_admin.has_add_permission(request) is False
        assert generated_admin.has_change_permission(request) is False
        assert generated_admin.has_delete_permission(request) is False


@pytest.mark.django_db
def test_disclaimer_add_requires_permission_and_missing_singleton(django_user_model: type) -> None:
    """Singleton absence cannot bypass Django's model-level add permission."""

    request = RequestFactory().get("/admin/share/")
    disclaimer_admin = admin.site._registry[ShareDisclaimerConfigModel]
    request.user = django_user_model.objects.create_user(username="share-staff", is_staff=True)
    with patch("apps.share.interface.admin.has_share_disclaimer_config", return_value=False):
        assert disclaimer_admin.has_add_permission(request) is False

    request.user = django_user_model.objects.create_superuser(
        username="share-disclaimer-root",
        email="disclaimer@example.com",
        password="test-password",
    )
    with patch("apps.share.interface.admin.has_share_disclaimer_config", return_value=False):
        assert disclaimer_admin.has_add_permission(request) is True
    with patch("apps.share.interface.admin.has_share_disclaimer_config", return_value=True):
        assert disclaimer_admin.has_add_permission(request) is False
    assert disclaimer_admin.has_delete_permission(request) is False
