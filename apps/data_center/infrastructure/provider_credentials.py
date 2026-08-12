"""Config Center-owned provider credential references.

Provider metadata remains owned by Data Center. Secret material is addressed
through deterministic Config Center references and is never stored on the
provider row or in a second encrypted side table.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from django.db import transaction

from core.integration.config_secret_store import (
    config_secret_present,
    persist_config_secret,
    resolve_config_secret,
)

from .models import ProviderConfigModel


class ProviderCredentialEncryptionUnavailable(ValueError):
    """Raised when Config Center cannot encrypt a provider credential."""


@dataclass(frozen=True)
class ProviderCredentialStatus:
    """Non-secret credential presence and stable reference metadata."""

    provider_id: int
    credential_ref: str
    has_api_key: bool
    has_api_secret: bool


def credential_ref_for_provider(provider_id: int) -> str:
    """Return the stable aggregate reference for one provider credential pair."""

    return f"config_center.data_center.provider.{provider_id}.credentials"


def api_key_ref_for_provider(provider_id: int) -> str:
    """Return the Config Center reference for one provider API key."""

    return f"{credential_ref_for_provider(provider_id)}.api_key"


def api_secret_ref_for_provider(provider_id: int) -> str:
    """Return the Config Center reference for one provider API secret."""

    return f"{credential_ref_for_provider(provider_id)}.api_secret"


class ProviderCredentialStore:
    """Resolve and persist provider secrets through Config Center public ports."""

    @staticmethod
    def _provider_id(provider: ProviderConfigModel) -> int:
        if provider.pk is None:
            raise ValueError("Provider must be saved before credentials are accessed")
        return int(provider.pk)

    def has_record(self, provider: ProviderConfigModel) -> bool:
        """Return whether Config Center owns either provider secret."""

        status = self.status(provider)
        return status.has_api_key or status.has_api_secret

    def status(self, provider: ProviderConfigModel) -> ProviderCredentialStatus:
        """Return presence flags without resolving either secret value."""

        provider_id = self._provider_id(provider)
        has_api_key = config_secret_present(api_key_ref_for_provider(provider_id))
        has_api_secret = config_secret_present(api_secret_ref_for_provider(provider_id))
        return ProviderCredentialStatus(
            provider_id=provider_id,
            credential_ref=(
                credential_ref_for_provider(provider_id) if has_api_key or has_api_secret else ""
            ),
            has_api_key=has_api_key,
            has_api_secret=has_api_secret,
        )

    def statuses(
        self, providers: Iterable[ProviderConfigModel]
    ) -> dict[int, ProviderCredentialStatus]:
        """Build non-secret status metadata for a provider collection."""

        return {
            int(provider.pk): self.status(provider)
            for provider in providers
            if provider.pk is not None
        }

    def statuses_from_rows(
        self, rows: Iterable[Mapping[str, object]]
    ) -> dict[int, ProviderCredentialStatus]:
        """Build status metadata from a read-only provider-id projection."""

        statuses: dict[int, ProviderCredentialStatus] = {}
        for row in rows:
            raw_id = row.get("id")
            if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
                continue
            provider_id = int(raw_id)
            has_api_key = config_secret_present(api_key_ref_for_provider(provider_id))
            has_api_secret = config_secret_present(api_secret_ref_for_provider(provider_id))
            statuses[provider_id] = ProviderCredentialStatus(
                provider_id=provider_id,
                credential_ref=(
                    credential_ref_for_provider(provider_id)
                    if has_api_key or has_api_secret
                    else ""
                ),
                has_api_key=has_api_key,
                has_api_secret=has_api_secret,
            )
        return statuses

    def resolve(self, provider: ProviderConfigModel) -> tuple[str, str, str]:
        """Resolve one provider's exact Config Center-owned secret pair."""

        provider_id = self._provider_id(provider)
        api_key = resolve_config_secret(api_key_ref_for_provider(provider_id))
        api_secret = resolve_config_secret(api_secret_ref_for_provider(provider_id))
        return (
            api_key,
            api_secret,
            credential_ref_for_provider(provider_id) if api_key or api_secret else "",
        )

    def persist(
        self,
        provider: ProviderConfigModel,
        *,
        api_key: str | None,
        api_secret: str | None,
    ) -> str:
        """Atomically replace explicitly supplied secrets in Config Center."""

        provider_id = self._provider_id(provider)
        try:
            with transaction.atomic():
                if api_key is not None:
                    persist_config_secret(api_key_ref_for_provider(provider_id), api_key)
                if api_secret is not None:
                    persist_config_secret(api_secret_ref_for_provider(provider_id), api_secret)
        except ValueError as exc:
            raise ProviderCredentialEncryptionUnavailable(str(exc)) from exc
        return self.status(provider).credential_ref


__all__ = [
    "ProviderCredentialEncryptionUnavailable",
    "ProviderCredentialStatus",
    "ProviderCredentialStore",
    "api_key_ref_for_provider",
    "api_secret_ref_for_provider",
    "credential_ref_for_provider",
]
