"""Typed runtime projection for Config Center-owned backup delivery secrets."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.account.infrastructure.models import SystemSettingsModel
from apps.config_center.application.public import (
    get_backup_delivery_runtime_payload,
    resolve_config_secret,
)
from apps.config_center.domain.backup_delivery import (
    BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
    BACKUP_SMTP_PASSWORD_SECRET_REF,
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


class BackupDeliveryRuntimeSettings:
    """Ephemeral backup settings with secrets resolved from canonical refs."""

    __slots__ = ("_archive_password", "_settings", "_smtp_password")
    _archive_password: str
    _settings: SystemSettingsModel
    _smtp_password: str

    def __init__(
        self,
        *,
        settings_obj: SystemSettingsModel,
        archive_password: str,
        smtp_password: str,
    ) -> None:
        object.__setattr__(self, "_settings", settings_obj)
        object.__setattr__(self, "_archive_password", archive_password)
        object.__setattr__(self, "_smtp_password", smtp_password)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._settings, name)

    def __setattr__(self, name: str, value: object) -> None:
        if name in self.__slots__:
            object.__setattr__(self, name, value)
            return
        setattr(self._settings, name, value)

    @property
    def archive_password(self) -> str:
        """Return the ephemeral archive password for the backup worker."""

        return self._archive_password

    @property
    def smtp_password(self) -> str:
        """Return the ephemeral SMTP password for the backup worker."""

        return self._smtp_password

    def is_backup_due(self, now: datetime | None = None) -> bool:
        """Return whether a fully configured backup delivery is due."""

        if not self.backup_enabled or not self.backup_email or not self.archive_password:
            return False
        current = now or datetime.now(UTC)
        if self.backup_last_sent_at is None:
            return True
        return bool((current - self.backup_last_sent_at).days >= self.backup_interval_days)


def _resolve_exact_secret(*, actual_ref: object, expected_ref: str) -> str:
    if actual_ref != expected_ref:
        return ""
    try:
        return resolve_config_secret(expected_ref)
    except (RuntimeError, TypeError, ValueError):
        return ""


def get_backup_delivery_settings(
    *,
    base_settings: SystemSettingsModel | None = None,
) -> BackupDeliveryRuntimeSettings:
    """Resolve policy/state plus canonical Config Center secrets for runtime."""

    settings_obj = base_settings or SystemSettingsModel.get_settings_for_read()
    payload = get_backup_delivery_runtime_payload()
    for field_name in _BACKUP_POLICY_FIELDS + _BACKUP_STATE_FIELDS:
        if field_name in payload:
            setattr(settings_obj, field_name, payload[field_name])
    return BackupDeliveryRuntimeSettings(
        settings_obj=settings_obj,
        archive_password=_resolve_exact_secret(
            actual_ref=payload.get("backup_archive_password_ref"),
            expected_ref=BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
        ),
        smtp_password=_resolve_exact_secret(
            actual_ref=payload.get("backup_smtp_password_ref"),
            expected_ref=BACKUP_SMTP_PASSWORD_SECRET_REF,
        ),
    )


def get_backup_delivery_payload() -> dict[str, Any]:
    """Return the non-secret backup contract for diagnostics and readiness."""

    try:
        return get_backup_delivery_runtime_payload()
    except RuntimeError:
        settings_obj = SystemSettingsModel.get_settings_for_read()
        return {
            **{
                field_name: getattr(settings_obj, field_name)
                for field_name in _BACKUP_POLICY_FIELDS + _BACKUP_STATE_FIELDS
            },
            "backup_archive_password_ref": BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
            "backup_smtp_password_ref": BACKUP_SMTP_PASSWORD_SECRET_REF,
            "policy_source": "system_settings_compatibility",
            "state_source": "system_settings_compatibility",
        }


__all__ = [
    "BackupDeliveryRuntimeSettings",
    "get_backup_delivery_payload",
    "get_backup_delivery_settings",
]
