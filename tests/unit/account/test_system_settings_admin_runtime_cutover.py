"""Guardrails for the compatibility SystemSettings Django Admin surface."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.contrib import admin

from apps.account.interface.admin import (
    SYSTEM_SETTINGS_TYPED_RUNTIME_FIELDS,
    SystemSettingsAdminForm,
    SystemSettingsModelAdmin,
)
from apps.config_center.infrastructure.models import SystemSettingsModel


def _fieldset_names(fieldsets: Iterable[tuple[str, dict[str, Any]]]) -> set[str]:
    """Flatten Django Admin fieldset field names for a structural assertion."""

    names: set[str] = set()
    for _title, options in fieldsets:
        names.update(str(name) for name in options.get("fields", ()))
    return names


def test_system_settings_admin_form_excludes_typed_runtime_fields() -> None:
    """The compatibility singleton Admin must not accept typed runtime writes."""

    assert not SYSTEM_SETTINGS_TYPED_RUNTIME_FIELDS.intersection(
        SystemSettingsAdminForm.base_fields
    )


def test_system_settings_admin_excludes_account_runtime_fields() -> None:
    """Account governance writes must use Config Center/TUI, not compatibility Admin."""

    account_fields = {
        "require_user_approval",
        "auto_approve_first_admin",
        "default_mcp_enabled",
        "allow_token_plaintext_view",
        "user_agreement_content",
        "risk_warning_content",
        "notes",
    }
    assert not account_fields.intersection(SystemSettingsAdminForm.base_fields)


def test_system_settings_admin_fieldsets_do_not_expose_typed_runtime_fields() -> None:
    """Admin operators are directed to Config Center/TUI for runtime settings."""

    field_names = _fieldset_names(SystemSettingsModelAdmin.fieldsets or ())
    assert not SYSTEM_SETTINGS_TYPED_RUNTIME_FIELDS.intersection(field_names)
    assert "runtime_config_notice" in field_names
    assert "runtime_config_notice" in SystemSettingsModelAdmin.readonly_fields


def test_system_settings_legacy_singleton_is_not_registered_in_admin() -> None:
    """Human writes must use Config Center/TUI instead of the legacy ORM model."""

    assert not admin.site.is_registered(SystemSettingsModel)
