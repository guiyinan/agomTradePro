"""Encrypted provider credential storage owned by Data Center."""

from __future__ import annotations

from django.db import models


class ProviderCredentialModel(models.Model):
    """One encrypted credential record for a provider configuration.

    ``ProviderConfigModel`` is retained as a migration-era compatibility
    projection. New writes must use this table; the legacy plaintext columns
    are only read by the explicit migration fallback in the repository.
    """

    provider = models.OneToOneField(
        "data_center.ProviderConfigModel",
        on_delete=models.CASCADE,
        related_name="credential_record",
    )
    credential_ref = models.CharField(max_length=300, unique=True)
    api_key_encrypted = models.TextField(blank=True)
    api_secret_encrypted = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_provider_credential"
        verbose_name = "Provider Credential"
        verbose_name_plural = "Provider Credentials"

    def __str__(self) -> str:
        """Return only the stable reference, never a credential value."""

        return self.credential_ref
