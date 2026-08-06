"""Compatibility projection for the Config Center-owned backup contract."""

from __future__ import annotations

from typing import Any

from apps.account.infrastructure.models import SystemSettingsModel
from apps.config_center.application.public import get_backup_delivery_runtime_payload

_BACKUP_POLICY_FIELDS: tuple[str, ...] = (
    "backup_enabled",
    "backup_email",
    "backup_app_base_url",
    "backup_mail_from_email",
    "backup_smtp_host",
    "backup_smtp_port",
    "backup_smtp_username",
    "backup_smtp_use_tls",
    "backup_smtp_use_ssl",
    "backup_interval_days",
    "backup_link_ttl_days",
    "backup_password_hint",
)
_BACKUP_STATE_FIELDS: tuple[str, ...] = (
    "backup_last_sent_at",
    "backup_download_token_digest",
    "backup_download_token_expires_at",
    "backup_download_consumed_at",
)


def get_backup_delivery_settings(
    *,
    base_settings: SystemSettingsModel | None = None,
) -> SystemSettingsModel:
    """Return a legacy-shaped read model backed by the typed policy/state.

    The old model remains a compatibility shape for backup infrastructure.  It
    is never used as the owner once a typed profile/state row is available.
    """

    settings_obj = base_settings or SystemSettingsModel.get_settings_for_read()
    try:
        payload = get_backup_delivery_runtime_payload()
    except RuntimeError:
        return settings_obj
    for field_name in _BACKUP_POLICY_FIELDS + _BACKUP_STATE_FIELDS:
        if field_name in payload:
            setattr(settings_obj, field_name, payload[field_name])
    if payload.get("backup_archive_password_ref") != "system_settings.backup_password_encrypted":
        settings_obj.backup_password_encrypted = ""
    if payload.get("backup_smtp_password_ref") != "system_settings.backup_smtp_password_encrypted":
        settings_obj.backup_smtp_password_encrypted = ""
    return settings_obj


def get_backup_delivery_payload() -> dict[str, Any]:
    """Return the non-ORM backup contract for diagnostics and readiness."""

    try:
        return get_backup_delivery_runtime_payload()
    except RuntimeError:
        settings_obj = SystemSettingsModel.get_settings_for_read()
        return {
            **{
                field_name: getattr(settings_obj, field_name)
                for field_name in _BACKUP_POLICY_FIELDS + _BACKUP_STATE_FIELDS
            },
            "policy_source": "system_settings_compatibility",
            "state_source": "system_settings_compatibility",
        }


__all__ = ["get_backup_delivery_payload", "get_backup_delivery_settings"]
