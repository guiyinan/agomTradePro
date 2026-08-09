"""Compatibility projection for the Config Center-owned backup contract."""

from __future__ import annotations

from typing import Any

from apps.account.infrastructure.system_settings_projection import SystemSettingsProjection
from apps.config_center.application.public import (
    get_backup_delivery_runtime_payload,
    resolve_config_secret,
)

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


def _project_secret(
    settings_obj: SystemSettingsProjection,
    *,
    secret_ref: object,
    attach_name: str,
) -> None:
    """Resolve a Config Center ref into an ephemeral compatibility projection."""

    normalized_ref = str(secret_ref or "").strip()
    if not normalized_ref:
        return
    try:
        plaintext = resolve_config_secret(normalized_ref)
        if plaintext:
            attach = getattr(settings_obj, attach_name)
            attach(plaintext)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        # A missing deployment key must remain a blocked, empty projection;
        # never re-open the legacy column as a silent bypass.
        return


def get_backup_delivery_settings(
    *,
    base_settings: SystemSettingsProjection | None = None,
) -> SystemSettingsProjection:
    """Return a legacy-shaped read model backed by the typed policy/state.

    The old model remains a compatibility shape for backup infrastructure.  It
    is never used as the owner once a typed profile/state row is available.
    """

    settings_obj = base_settings or SystemSettingsProjection()
    try:
        payload = get_backup_delivery_runtime_payload()
    except RuntimeError:
        return settings_obj
    for field_name in _BACKUP_POLICY_FIELDS + _BACKUP_STATE_FIELDS:
        if field_name in payload:
            setattr(settings_obj, field_name, payload[field_name])
    _project_secret(
        settings_obj,
        secret_ref=payload.get("backup_archive_password_ref"),
        attach_name="attach_backup_password",
    )
    _project_secret(
        settings_obj,
        secret_ref=payload.get("backup_smtp_password_ref"),
        attach_name="attach_backup_smtp_password",
    )
    return settings_obj


def get_backup_delivery_payload() -> dict[str, Any]:
    """Return the non-ORM backup contract for diagnostics and readiness."""

    try:
        return get_backup_delivery_runtime_payload()
    except RuntimeError:
        return {
            "status": "blocked",
            "must_not_use_for_decision": True,
            "blocked_reason": "runtime_config_snapshot_unavailable",
            "policy_source": "blocked",
            "state_source": "blocked",
        }


__all__ = ["get_backup_delivery_payload", "get_backup_delivery_settings"]
