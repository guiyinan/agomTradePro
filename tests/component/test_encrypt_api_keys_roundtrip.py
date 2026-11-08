"""Encrypted persistence contracts after removal of plaintext key storage."""

import pytest

from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.ai_provider.infrastructure.repositories import AIProviderRepository
from shared.infrastructure.crypto import FieldEncryptionService


@pytest.mark.django_db
def test_repository_create_update_and_blank_update_keep_only_encrypted_keys(settings) -> None:
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    repository = AIProviderRepository()
    original = "sk-ref06-original-credential"
    rotated = "sk-ref06-rotated-credential"

    provider = repository.create(
        name="ref06-encrypted-roundtrip",
        provider_type="custom",
        base_url="https://example.invalid/v1",
        api_key=original,
        default_model="gpt-4o-mini",
    )

    assert "api_key" not in {field.name for field in AIProviderConfig._meta.local_concrete_fields}
    assert provider.api_key_encrypted.startswith(FieldEncryptionService.PREFIX)
    assert repository.get_api_key(provider) == original

    original_ciphertext = provider.api_key_encrypted
    assert repository.update(int(provider.pk), api_key=rotated) is True
    provider.refresh_from_db()
    assert provider.api_key_encrypted != original_ciphertext
    assert repository.get_api_key(provider) == rotated

    rotated_ciphertext = provider.api_key_encrypted
    assert repository.update(int(provider.pk), api_key="") is True
    provider.refresh_from_db()
    assert provider.api_key_encrypted == rotated_ciphertext
    assert repository.get_api_key(provider) == rotated
