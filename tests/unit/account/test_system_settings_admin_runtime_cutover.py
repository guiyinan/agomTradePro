"""Guardrails for the retired SystemSettings Django Admin surface."""

from __future__ import annotations

from django.contrib import admin

from apps.account.interface import admin as account_admin
from apps.config_center.infrastructure.models import SystemSettingsModel


def test_system_settings_legacy_singleton_is_not_registered_in_admin() -> None:
    """The retired compatibility surface must have no executable Admin class."""

    assert not admin.site.is_registered(SystemSettingsModel)
    assert not hasattr(account_admin, "SystemSettingsAdminForm")
    assert not hasattr(account_admin, "SystemSettingsModelAdmin")
