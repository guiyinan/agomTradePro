"""Fail-closed encrypted secret store for Config Center-owned references."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cryptography.fernet import InvalidToken
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from shared.infrastructure.crypto import FieldEncryptionService

from .secret_models import ConfigCenterSecretModel

_SECRET_REF_PATTERN = re.compile(r"^config_center\.[a-z0-9][a-z0-9_.-]{0,298}$")


class ConfigCenterSecretUnavailable(ValueError):
    """Raised when a new secret cannot be encrypted with the deployment key."""


@dataclass(frozen=True)
class ConfigCenterSecretStatus:
    """Non-secret presence metadata for one stable secret reference."""

    secret_ref: str
    present: bool


def validate_secret_ref(secret_ref: str) -> str:
    """Validate and normalize a Config Center-owned secret reference."""

    normalized = str(secret_ref or "").strip()
    if not _SECRET_REF_PATTERN.fullmatch(normalized):
        raise ValueError("invalid_config_center_secret_ref")
    return normalized


class ConfigCenterSecretStore:
    """Encrypt, resolve, and replace Config Center-owned secret values."""

    def __init__(self) -> None:
        self._crypto: FieldEncryptionService | None = None

    @property
    def _crypto_service(self) -> FieldEncryptionService:
        """Return the configured field-encryption service or fail closed."""

        if self._crypto is None:
            try:
                self._crypto = FieldEncryptionService()
            except ValueError as exc:
                raise ConfigCenterSecretUnavailable(
                    "AGOMTRADEPRO_ENCRYPTION_KEY not configured"
                ) from exc
        return self._crypto

    @staticmethod
    def _record(secret_ref: str) -> ConfigCenterSecretModel | None:
        return ConfigCenterSecretModel._default_manager.filter(secret_ref=secret_ref).first()

    def status(self, secret_ref: str) -> ConfigCenterSecretStatus:
        """Return presence without decrypting or exposing the secret."""

        normalized = validate_secret_ref(secret_ref)
        record = self._record(normalized)
        return ConfigCenterSecretStatus(
            secret_ref=normalized,
            present=bool(record is not None and record.encrypted_value),
        )

    def resolve(self, secret_ref: str) -> str:
        """Resolve one secret, returning an empty value when unavailable."""

        normalized = validate_secret_ref(secret_ref)
        record = self._record(normalized)
        if record is None or not record.encrypted_value:
            return ""
        try:
            return self._crypto_service.decrypt(record.encrypted_value, suppress_warning=True)
        except (
            ConfigCenterSecretUnavailable,
            ImproperlyConfigured,
            InvalidToken,
            TypeError,
            ValueError,
        ):
            return ""

    def persist(self, secret_ref: str, value: str | None) -> ConfigCenterSecretStatus:
        """Create, replace, or explicitly clear one encrypted secret."""

        normalized = validate_secret_ref(secret_ref)
        normalized_value = str(value) if value is not None else None
        with transaction.atomic():
            if normalized_value is not None and not normalized_value:
                ConfigCenterSecretModel._default_manager.filter(secret_ref=normalized).delete()
            elif normalized_value is not None:
                encrypted = self._crypto_service.encrypt(normalized_value)
                ConfigCenterSecretModel._default_manager.update_or_create(
                    secret_ref=normalized,
                    defaults={"encrypted_value": encrypted},
                )
        return self.status(normalized)


__all__ = [
    "ConfigCenterSecretStore",
    "ConfigCenterSecretStatus",
    "ConfigCenterSecretUnavailable",
    "validate_secret_ref",
]
