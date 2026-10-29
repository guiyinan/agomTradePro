"""Real round-trip contracts for the AI provider key-encryption command."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.ai_provider.infrastructure.repositories import AIProviderRepository
from shared.infrastructure.crypto import FieldEncryptionService


def _create_plaintext_provider(name: str, api_key: str) -> AIProviderConfig:
    return AIProviderConfig.objects.create(
        name=name,
        provider_type="custom",
        base_url="https://example.invalid/v1",
        api_key=api_key,
        default_model="gpt-4o-mini",
        api_mode="dual",
        fallback_enabled=True,
    )


@pytest.mark.django_db
def test_command_encrypts_with_verified_roundtrip_and_clears_plaintext(settings) -> None:
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    plaintext = "sk-live-roundtrip-secret-0001"
    provider = _create_plaintext_provider("ref06-roundtrip", plaintext)

    call_command("encrypt_api_keys")

    provider.refresh_from_db()
    assert provider.api_key == ""
    assert provider.api_key_encrypted.startswith(FieldEncryptionService.PREFIX)
    assert FieldEncryptionService().decrypt(provider.api_key_encrypted) == plaintext
    assert AIProviderRepository().get_api_key(provider) == plaintext


@pytest.mark.django_db
def test_command_rerun_is_idempotent_and_preserves_ciphertext(settings) -> None:
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    provider = _create_plaintext_provider("ref06-idempotent", "sk-live-idempotent-0002")

    call_command("encrypt_api_keys")
    provider.refresh_from_db()
    first_ciphertext = provider.api_key_encrypted
    assert first_ciphertext

    output = StringIO()
    call_command("encrypt_api_keys", stdout=output)

    provider.refresh_from_db()
    assert provider.api_key_encrypted == first_ciphertext
    assert "No API keys found to encrypt." in output.getvalue()


@pytest.mark.django_db
def test_command_dry_run_leaves_plaintext_row_untouched(settings) -> None:
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    plaintext = "sk-live-dry-run-0003"
    provider = _create_plaintext_provider("ref06-dry-run", plaintext)

    call_command("encrypt_api_keys", dry_run=True)

    provider.refresh_from_db()
    assert provider.api_key == plaintext
    assert provider.api_key_encrypted == ""


@pytest.mark.django_db
def test_command_output_never_contains_key_material(settings) -> None:
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    plaintext = "sk-live-masking-0004"
    _create_plaintext_provider("ref06-masking", plaintext)

    output = StringIO()
    call_command("encrypt_api_keys", stdout=output)

    assert plaintext not in output.getvalue()
    assert "sk-live" not in output.getvalue()
