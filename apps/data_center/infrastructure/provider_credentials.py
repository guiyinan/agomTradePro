"""Provider credential encryption and migration boundary.

The Data Center provider repository is the only runtime boundary that turns
stored provider credentials into the domain ``ProviderConfig``.  The legacy
``ProviderConfigModel.api_key``/``api_secret`` columns remain readable only so
an explicit migration can be performed without losing an existing setup.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from cryptography.fernet import InvalidToken
from django.db import transaction

from shared.infrastructure.crypto import FieldEncryptionService

from .models import ProviderConfigModel
from .provider_credential_models import ProviderCredentialModel

logger = logging.getLogger(__name__)
_UNUSABLE_CREDENTIAL_FINGERPRINTS: set[str] = set()


class ProviderCredentialEncryptionUnavailable(ValueError):
    """Raised when a new credential cannot be encrypted at rest."""


@dataclass(frozen=True)
class ProviderCredentialStatus:
    """Non-secret credential presence and stable reference metadata."""

    provider_id: int
    credential_ref: str
    has_api_key: bool
    has_api_secret: bool


def credential_ref_for_provider(provider_id: int) -> str:
    """Return the stable secret reference for one provider row."""

    return f"data_center.provider.{provider_id}.credentials"


class ProviderCredentialStore:
    """Encrypt, resolve, and migrate provider credentials."""

    def __init__(self) -> None:
        self._crypto: FieldEncryptionService | None = None

    @property
    def _crypto_service(self) -> FieldEncryptionService:
        """Return the configured encryption service or fail closed."""

        if self._crypto is None:
            try:
                self._crypto = FieldEncryptionService()
            except ValueError as exc:
                raise ProviderCredentialEncryptionUnavailable(
                    "AGOMTRADEPRO_ENCRYPTION_KEY not configured"
                ) from exc
        return self._crypto

    def _encrypt(self, value: str) -> str:
        return self._crypto_service.encrypt(value) if value else ""

    def encryption_available(self) -> bool:
        """Return whether new credential writes can be encrypted."""

        try:
            _ = self._crypto_service
        except ProviderCredentialEncryptionUnavailable:
            return False
        return True

    def _decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            decrypted = self._crypto_service.decrypt(value, suppress_warning=True)
            if not value.startswith(FieldEncryptionService.PREFIX) and decrypted == value:
                return ""
            return decrypted
        except (InvalidToken, ValueError):
            fingerprint = hashlib.sha1(
                value.encode("utf-8"),
                usedforsecurity=False,
            ).hexdigest()[:12]
            if fingerprint not in _UNUSABLE_CREDENTIAL_FINGERPRINTS:
                logger.warning("Provider credential cannot be decrypted in the current environment")
                _UNUSABLE_CREDENTIAL_FINGERPRINTS.add(fingerprint)
            return ""
        except Exception:
            logger.exception("Unable to decrypt Data Center provider credential")
            return ""

    @staticmethod
    def _record(provider: ProviderConfigModel) -> ProviderCredentialModel | None:
        if provider.pk is None:
            return None
        return (
            ProviderCredentialModel._default_manager.filter(provider_id=provider.pk)
            .order_by("pk")
            .first()
        )

    def has_record(self, provider: ProviderConfigModel) -> bool:
        """Return whether the provider already has an encrypted record."""

        return self._record(provider) is not None

    def status(self, provider: ProviderConfigModel) -> ProviderCredentialStatus:
        """Return presence flags without decrypting or exposing secrets."""

        record = self._record(provider)
        return ProviderCredentialStatus(
            provider_id=int(provider.pk or 0),
            credential_ref=(
                record.credential_ref
                if record is not None
                else (
                    credential_ref_for_provider(int(provider.pk))
                    if provider.api_key or provider.api_secret
                    else ""
                )
            ),
            has_api_key=bool(
                (record is not None and record.api_key_encrypted)
                or (record is None and provider.api_key)
            ),
            has_api_secret=bool(
                (record is not None and record.api_secret_encrypted)
                or (record is None and provider.api_secret)
            ),
        )

    def statuses(
        self, providers: Iterable[ProviderConfigModel]
    ) -> dict[int, ProviderCredentialStatus]:
        """Build presence flags for a provider collection with bounded queries."""

        rows = list(providers)
        provider_ids = [int(provider.pk) for provider in rows if provider.pk is not None]
        records = {
            int(record.provider_id): record
            for record in ProviderCredentialModel._default_manager.filter(
                provider_id__in=provider_ids
            )
        }
        return {
            int(provider.pk): self._status_from_record(provider, records.get(int(provider.pk)))
            for provider in rows
            if provider.pk is not None
        }

    def statuses_from_rows(
        self, rows: Iterable[Mapping[str, object]]
    ) -> dict[int, ProviderCredentialStatus]:
        """Build presence flags from a read-only ORM values projection."""

        row_list = list(rows)
        provider_ids: list[int] = []
        for row in row_list:
            raw_id = row.get("id")
            if isinstance(raw_id, (int, str)):
                provider_ids.append(int(raw_id))
        records = {
            int(record.provider_id): record
            for record in ProviderCredentialModel._default_manager.filter(
                provider_id__in=provider_ids
            )
        }
        statuses: dict[int, ProviderCredentialStatus] = {}
        for row in row_list:
            raw_id = row.get("id")
            if not isinstance(raw_id, (int, str)):
                continue
            provider_id = int(raw_id)
            record = records.get(provider_id)
            statuses[provider_id] = ProviderCredentialStatus(
                provider_id=provider_id,
                credential_ref=(
                    record.credential_ref
                    if record is not None
                    else (
                        credential_ref_for_provider(provider_id)
                        if row.get("api_key") or row.get("api_secret")
                        else ""
                    )
                ),
                has_api_key=bool(
                    (record is not None and record.api_key_encrypted)
                    or (record is None and row.get("api_key"))
                ),
                has_api_secret=bool(
                    (record is not None and record.api_secret_encrypted)
                    or (record is None and row.get("api_secret"))
                ),
            )
        return statuses

    @staticmethod
    def _status_from_record(
        provider: ProviderConfigModel,
        record: ProviderCredentialModel | None,
    ) -> ProviderCredentialStatus:
        return ProviderCredentialStatus(
            provider_id=int(provider.pk or 0),
            credential_ref=(
                record.credential_ref
                if record is not None
                else (
                    credential_ref_for_provider(int(provider.pk))
                    if provider.api_key or provider.api_secret
                    else ""
                )
            ),
            has_api_key=bool(
                (record is not None and record.api_key_encrypted)
                or (record is None and provider.api_key)
            ),
            has_api_secret=bool(
                (record is not None and record.api_secret_encrypted)
                or (record is None and provider.api_secret)
            ),
        )

    def resolve(self, provider: ProviderConfigModel) -> tuple[str, str, str]:
        """Resolve credentials for runtime use, preferring encrypted storage.

        If an encrypted value exists but cannot be decrypted, the value is
        treated as unavailable; the legacy plaintext column is not used as a
        silent bypass in that case.
        """

        record = self._record(provider)
        if record is not None:
            api_key = self._decrypt(record.api_key_encrypted)
            api_secret = self._decrypt(record.api_secret_encrypted)
            if record.api_key_encrypted and not api_key:
                api_key = ""
            elif not record.api_key_encrypted:
                api_key = provider.api_key
            if record.api_secret_encrypted and not api_secret:
                api_secret = ""
            elif not record.api_secret_encrypted:
                api_secret = provider.api_secret
            return api_key, api_secret, record.credential_ref
        return (
            provider.api_key,
            provider.api_secret,
            (
                credential_ref_for_provider(int(provider.pk))
                if provider.pk is not None and (provider.api_key or provider.api_secret)
                else ""
            ),
        )

    def persist(
        self,
        provider: ProviderConfigModel,
        *,
        api_key: str | None,
        api_secret: str | None,
        allow_legacy_fallback: bool = False,
    ) -> str:
        """Persist credentials encrypted and clear plaintext projections.

        ``None`` means preserve the existing credential. Empty strings are an
        explicit clear. Legacy plaintext is tolerated only when no credential
        change was requested and encryption is unavailable; a new or changed
        secret never falls back to plaintext storage.
        """

        if provider.pk is None:
            raise ValueError("Provider must be saved before credentials are persisted")
        existing_record = self._record(provider)
        if api_key is None and api_secret is None and existing_record is not None:
            return existing_record.credential_ref
        current_key, current_secret, current_ref = self.resolve(provider)
        target_key = current_key if api_key is None else api_key
        target_secret = current_secret if api_secret is None else api_secret
        if not target_key and not target_secret:
            if existing_record is not None:
                existing_record.delete()
            provider.api_key = ""
            provider.api_secret = ""
            provider.save(update_fields=["api_key", "api_secret", "updated_at"])
            return ""

        try:
            encrypted_key = self._encrypt(target_key)
            encrypted_secret = self._encrypt(target_secret)
        except ProviderCredentialEncryptionUnavailable:
            legacy_unchanged = (
                allow_legacy_fallback
                and existing_record is None
                and bool(provider.api_key or provider.api_secret)
                and target_key == provider.api_key
                and target_secret == provider.api_secret
            )
            if legacy_unchanged:
                return current_ref or credential_ref_for_provider(int(provider.pk))
            raise

        record, _created = ProviderCredentialModel._default_manager.update_or_create(
            provider=provider,
            defaults={
                "credential_ref": credential_ref_for_provider(int(provider.pk)),
                "api_key_encrypted": encrypted_key,
                "api_secret_encrypted": encrypted_secret,
            },
        )
        provider.api_key = ""
        provider.api_secret = ""
        provider.save(update_fields=["api_key", "api_secret", "updated_at"])
        return record.credential_ref

    def migrate_legacy(self, provider: ProviderConfigModel, *, dry_run: bool = False) -> bool:
        """Encrypt legacy plaintext columns for one provider."""

        if not provider.api_key and not provider.api_secret:
            return False
        if self._record(provider) is not None:
            return False
        if dry_run:
            _ = self._crypto_service
            return True
        with transaction.atomic():
            self.persist(
                provider,
                api_key=provider.api_key,
                api_secret=provider.api_secret,
            )
        return True
