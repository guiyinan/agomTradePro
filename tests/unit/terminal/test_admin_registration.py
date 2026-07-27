"""Terminal Admin discovery and permission regressions."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib import admin
from django.test import RequestFactory

from apps.terminal.interface.admin import (
    TerminalAuditLogAdmin,
    TerminalCommandAdmin,
    TerminalRuntimeSettingsAdmin,
)
from apps.terminal.models import (
    TerminalAuditLogORM,
    TerminalCommandORM,
    TerminalRuntimeSettingsORM,
)
from shared.infrastructure.django_admin import TypedModelAdmin


def test_terminal_models_are_registered_once_through_typed_admins() -> None:
    """Django autodiscovery exposes all Terminal governance models."""

    expected = {
        TerminalCommandORM: TerminalCommandAdmin,
        TerminalAuditLogORM: TerminalAuditLogAdmin,
        TerminalRuntimeSettingsORM: TerminalRuntimeSettingsAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)


@pytest.mark.django_db
def test_terminal_audit_admin_is_fully_immutable(django_user_model: type) -> None:
    """Terminal audit evidence cannot be fabricated, changed, or deleted in Admin."""

    user = django_user_model.objects.create_user(username="terminal-audit-viewer", is_staff=True)
    request = RequestFactory().get("/admin/terminal/")
    request.user = user
    audit_admin = admin.site._registry[TerminalAuditLogORM]

    assert audit_admin.has_add_permission(request) is False
    assert audit_admin.has_change_permission(request) is False
    assert audit_admin.has_delete_permission(request) is False


@pytest.mark.django_db
def test_runtime_settings_add_requires_permission_and_missing_singleton(
    django_user_model: type,
) -> None:
    """Singleton availability cannot bypass Django's model-level add permission."""

    request = RequestFactory().get("/admin/terminal/")
    settings_admin = admin.site._registry[TerminalRuntimeSettingsORM]
    request.user = django_user_model.objects.create_user(
        username="terminal-settings-staff",
        is_staff=True,
    )
    with patch(
        "apps.terminal.interface.admin.can_create_terminal_runtime_settings",
        return_value=True,
    ):
        assert settings_admin.has_add_permission(request) is False

    request.user = django_user_model.objects.create_superuser(
        username="terminal-settings-root",
        email="root@example.com",
        password="test-password",
    )
    with patch(
        "apps.terminal.interface.admin.can_create_terminal_runtime_settings",
        return_value=True,
    ):
        assert settings_admin.has_add_permission(request) is True
    with patch(
        "apps.terminal.interface.admin.can_create_terminal_runtime_settings",
        return_value=False,
    ):
        assert settings_admin.has_add_permission(request) is False
    assert settings_admin.has_delete_permission(request) is False
