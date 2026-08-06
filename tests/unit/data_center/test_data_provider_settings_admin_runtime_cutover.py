"""Guardrails for Data Center's legacy provider-settings Admin surface."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from apps.data_center.interface.admin import (
    DataProviderSettingsAdmin,
    DataProviderSettingsAdminForm,
)


def _fieldset_names(fieldsets: Iterable[tuple[str | None, dict[str, Any]]]) -> set[str]:
    """Flatten Django Admin fieldset field names for a structural assertion."""

    names: set[str] = set()
    for _title, options in fieldsets:
        names.update(str(name) for name in options.get("fields", ()))
    return names


def test_data_provider_settings_admin_form_excludes_typed_failover_fields() -> None:
    """The legacy singleton Admin must not accept typed provider runtime writes."""

    assert "default_source" not in DataProviderSettingsAdminForm.base_fields
    assert "enable_failover" not in DataProviderSettingsAdminForm.base_fields
    assert "failover_tolerance" not in DataProviderSettingsAdminForm.base_fields


def test_data_provider_settings_admin_exposes_typed_failover_as_read_only() -> None:
    """Admin operators are directed to Config Center/TUI for failover changes."""

    field_names = _fieldset_names(DataProviderSettingsAdmin.fieldsets or ())
    assert "default_source" not in field_names
    assert "enable_failover" not in field_names
    assert "failover_tolerance" not in field_names
    assert "typed_default_source" in field_names
    assert "typed_failover_enabled" in field_names
    assert "typed_failover_tolerance" in field_names
    assert "runtime_config_notice" in field_names
