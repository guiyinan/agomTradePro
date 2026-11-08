"""Regression meaning for old partial-migration command invocations after retirement."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ai_provider.infrastructure.repositories import AIProviderRepository
from shared.infrastructure.crypto import FieldEncryptionService


@pytest.mark.django_db
def test_retired_command_cannot_rewrite_an_already_usable_credential(settings) -> None:
    """Old retry/force invocations leave verified encrypted credentials untouched."""

    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    repository = AIProviderRepository()
    plaintext = "sk-ref06-existing-verified-credential"
    provider = repository.create(
        name="ref06-retired-command-preserves-key",
        provider_type="custom",
        base_url="https://example.invalid/v1",
        api_key=plaintext,
        default_model="gpt-4o-mini",
    )
    ciphertext = provider.api_key_encrypted
    empty_provider = repository.create(
        name="ref06-retired-command-leaves-empty-provider",
        provider_type="custom",
        base_url="https://empty.example.invalid/v1",
        api_key="",
        default_model="gpt-4o-mini",
    )

    with pytest.raises(CommandError, match="encrypt_api_keys is retired"):
        call_command("encrypt_api_keys", force=True)

    provider.refresh_from_db()
    empty_provider.refresh_from_db()
    assert provider.api_key_encrypted == ciphertext
    assert repository.get_api_key(provider) == plaintext
    assert empty_provider.api_key_encrypted == ""
