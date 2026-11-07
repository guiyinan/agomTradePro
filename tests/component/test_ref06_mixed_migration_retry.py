"""Persistence contract for partial AI provider credential migrations."""

from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ai_provider.infrastructure.models import AIProviderConfig
from shared.infrastructure.crypto import FieldEncryptionService


def _create_plaintext_provider(name: str, api_key: str) -> AIProviderConfig:
    """Create one legacy row for an isolated migration contract."""

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
def test_partial_migration_preserves_success_and_retries_only_failed_row(settings) -> None:
    """Keep committed rows encrypted and retry only plaintext rows after partial failure."""

    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    successful_plaintext = "sk-ref06-success-credential"
    failed_plaintext = "sk-ref06-retry-credential"
    successful_provider = _create_plaintext_provider(
        "ref06-partial-001-success",
        successful_plaintext,
    )
    failed_provider = _create_plaintext_provider(
        "ref06-partial-002-failure",
        failed_plaintext,
    )
    real_crypto = FieldEncryptionService()
    failing_crypto = Mock()

    def encrypt_with_one_failure(plaintext: str) -> str:
        if plaintext == failed_plaintext:
            raise RuntimeError("simulated_encryption_failure")
        return real_crypto.encrypt(plaintext)

    failing_crypto.encrypt.side_effect = encrypt_with_one_failure
    failing_crypto.is_encrypted.side_effect = real_crypto.is_encrypted
    failing_crypto.decrypt.side_effect = real_crypto.decrypt
    first_output = StringIO()

    with (
        patch(
            "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys."
            "get_encryption_service",
            return_value=failing_crypto,
        ),
        pytest.raises(CommandError, match=r"Failed to encrypt 1 provider\(s\)"),
    ):
        call_command("encrypt_api_keys", stdout=first_output)

    successful_provider.refresh_from_db()
    failed_provider.refresh_from_db()
    successful_ciphertext = successful_provider.api_key_encrypted

    assert successful_provider.api_key == ""
    assert successful_ciphertext.startswith(FieldEncryptionService.PREFIX)
    assert real_crypto.decrypt(successful_ciphertext) == successful_plaintext
    assert failed_provider.api_key == failed_plaintext
    assert failed_provider.api_key_encrypted == ""
    assert "Encrypted: 1" in first_output.getvalue()
    assert "Errors: 1" in first_output.getvalue()
    assert successful_plaintext not in first_output.getvalue()
    assert failed_plaintext not in first_output.getvalue()

    retry_output = StringIO()
    call_command("encrypt_api_keys", stdout=retry_output)

    successful_provider.refresh_from_db()
    failed_provider.refresh_from_db()

    assert successful_provider.api_key == ""
    assert successful_provider.api_key_encrypted == successful_ciphertext
    assert failed_provider.api_key == ""
    assert real_crypto.decrypt(failed_provider.api_key_encrypted) == failed_plaintext
    assert "Total providers: 1" in retry_output.getvalue()
    assert "Encrypted: 1" in retry_output.getvalue()
    assert "Errors: 0" not in retry_output.getvalue()
    assert failed_plaintext not in retry_output.getvalue()
