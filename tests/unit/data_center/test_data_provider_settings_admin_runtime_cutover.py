"""Guardrail for the retired provider-settings Admin surface."""

from __future__ import annotations

from django.contrib import admin

from apps.data_center.infrastructure.models import DataProviderSettingsModel
from apps.data_center.interface import admin as data_center_admin


def test_data_provider_settings_admin_is_unregistered() -> None:
    """The legacy singleton must not remain a human-readable or writable entrypoint."""

    assert DataProviderSettingsModel not in admin.site._registry
    assert not hasattr(data_center_admin, "DataProviderSettingsAdmin")
    assert not hasattr(data_center_admin, "DataProviderSettingsAdminForm")
    assert not hasattr(DataProviderSettingsModel, "load_for_read")
    assert not hasattr(DataProviderSettingsModel, "to_domain")
