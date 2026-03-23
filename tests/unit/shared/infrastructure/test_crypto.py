"""
Unit tests for field encryption service.

Tests the FieldEncryptionService class from shared.infrastructure.crypto.
"""
import os

import django
import pytest
from cryptography.fernet import InvalidToken
from django.conf import settings

from shared.infrastructure.crypto import (
    FieldEncryptionService,
    get_encryption_service,
    mask_api_key,
)


class TestFieldEncryptionService:
    """Test suite for FieldEncryptionService."""

    def test_generate_key(self):
        """Test key generation produces valid Fernet keys."""
        key = FieldEncryptionService.generate_key()
        assert isinstance(key, str)
        assert len(key) == 44  # Fernet keys are 44 bytes base64-encoded

    def test_init_with_explicit_key(self):
        """Test initialization with explicit key."""
        key = FieldEncryptionService.generate_key()
        service = FieldEncryptionService(encryption_key=key)
        assert service is not None
        assert service.fernet is not None

    def test_init_without_key_raises_error(self):
        """Test initialization without key raises ValueError."""
        # Clear environment variable
        original = os.environ.get('AGOMTRADEPRO_ENCRYPTION_KEY')
        original_setting = getattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY', None)
        os.environ.pop('AGOMTRADEPRO_ENCRYPTION_KEY', None)
        if hasattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY'):
            delattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY')

        try:
            with pytest.raises(ValueError, match="AGOMTRADEPRO_ENCRYPTION_KEY not configured"):
                FieldEncryptionService()
        finally:
            # Restore environment
            if original:
                os.environ['AGOMTRADEPRO_ENCRYPTION_KEY'] = original
            if original_setting is not None:
                setattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY', original_setting)

    def test_encrypt_decrypt_roundtrip(self):
        """Test encryption and decryption roundtrip."""
        key = FieldEncryptionService.generate_key()
        service = FieldEncryptionService(encryption_key=key)

        plaintext = "sk-1234567890abcdef"
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)

        assert decrypted == plaintext
        assert encrypted != plaintext
        assert encrypted.startswith(FieldEncryptionService.PREFIX)

    def test_encrypt_empty_string(self):
        """Test encrypting empty string."""
        key = FieldEncryptionService.generate_key()
        service = FieldEncryptionService(encryption_key=key)

        result = service.encrypt("")
        assert result == ""

    def test_decrypt_empty_string(self):
        """Test decrypting empty string."""
        key = FieldEncryptionService.generate_key()
        service = FieldEncryptionService(encryption_key=key)

        result = service.decrypt("")
        assert result == ""

    def test_decrypt_with_wrong_key_fails(self):
        """Test decryption with wrong key raises InvalidToken."""
        key1 = FieldEncryptionService.generate_key()
        key2 = FieldEncryptionService.generate_key()

        service1 = FieldEncryptionService(encryption_key=key1)
        service2 = FieldEncryptionService(encryption_key=key2)

        plaintext = "secret-api-key"
        encrypted = service1.encrypt(plaintext)

        with pytest.raises(InvalidToken):
            service2.decrypt(encrypted)

    def test_decrypt_plaintext_fallback(self):
        """Test that decrypting plaintext returns as-is."""
        key = FieldEncryptionService.generate_key()
        service = FieldEncryptionService(encryption_key=key)

        plaintext = "not-encrypted-value"
        result = service.decrypt(plaintext)

        # Should return as-is if not encrypted
        assert result == plaintext

    def test_is_encrypted(self):
        """Test is_encrypted method."""
        key = FieldEncryptionService.generate_key()
        service = FieldEncryptionService(encryption_key=key)

        plaintext = "test-value"
        encrypted = service.encrypt(plaintext)

        assert service.is_encrypted(encrypted) is True
        assert service.is_encrypted(plaintext) is False
        assert service.is_encrypted("") is False

    def test_encryption_produces_different_ciphertext(self):
        """Test that encrypting same value twice produces different ciphertext."""
        key = FieldEncryptionService.generate_key()
        service = FieldEncryptionService(encryption_key=key)

        plaintext = "same-value"
        encrypted1 = service.encrypt(plaintext)
        encrypted2 = service.encrypt(plaintext)

        # Ciphertext should be different due to random IV
        assert encrypted1 != encrypted2

        # But both should decrypt to the same value
        assert service.decrypt(encrypted1) == plaintext
        assert service.decrypt(encrypted2) == plaintext


class TestMaskApiKey:
    """Test suite for mask_api_key function."""

    def test_mask_standard_key(self):
        """Test masking a standard API key."""
        key = "sk-1234567890abcdefghijklmnop"
        masked = mask_api_key(key, visible_chars=8)

        assert masked.startswith("sk-12345")
        assert "*" in masked
        assert "1234567890abcdefghijklmnop" not in masked

    def test_mask_short_key(self):
        """Test masking a very short key."""
        key = "ab"
        masked = mask_api_key(key, visible_chars=4)

        assert masked == "***"

    def test_mask_empty_key(self):
        """Test masking an empty key."""
        assert mask_api_key("") == ""

    def test_mask_none_key(self):
        """Test masking None key."""
        assert mask_api_key(None) == ""

    def test_mask_custom_visible_chars(self):
        """Test masking with custom visible characters."""
        key = "sk-1234567890abcdefghijklmnop"
        masked = mask_api_key(key, visible_chars=15)

        assert masked.startswith("sk-1234567890ab")
        assert "*" in masked


class TestGetEncryptionService:
    """Test suite for get_encryption_service function."""

    def test_returns_service_when_key_configured(self):
        """Test that service is returned when key is configured."""
        key = FieldEncryptionService.generate_key()
        os.environ['AGOMTRADEPRO_ENCRYPTION_KEY'] = key

        # Update Django settings
        original_setting = getattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY', None)
        setattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY', key)

        try:
            service = get_encryption_service()
            assert service is not None
            assert isinstance(service, FieldEncryptionService)
        finally:
            os.environ.pop('AGOMTRADEPRO_ENCRYPTION_KEY', None)
            if original_setting is None:
                delattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY')
            else:
                setattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY', original_setting)

    def test_returns_none_when_key_not_configured(self):
        """Test that None is returned when key is not configured."""
        original_env = os.environ.get('AGOMTRADEPRO_ENCRYPTION_KEY')
        original_setting = getattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY', None)

        os.environ.pop('AGOMTRADEPRO_ENCRYPTION_KEY', None)
        if hasattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY'):
            delattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY')

        try:
            service = get_encryption_service()
            assert service is None
        finally:
            if original_env:
                os.environ['AGOMTRADEPRO_ENCRYPTION_KEY'] = original_env
            if original_setting:
                setattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY', original_setting)


class TestFieldEncryptionServiceMask:
    """Test suite for FieldEncryptionService.mask static method."""

    def test_mask_short_value(self):
        """Test masking of short values."""
        result = FieldEncryptionService.mask("short")
        assert result == "****"

    def test_mask_long_value(self):
        """Test masking of long values."""
        api_key = "sk-1234567890abcdefghijklmnop"
        result = FieldEncryptionService.mask(api_key, show_prefix=8, show_suffix=4)
        assert result == "sk-12345...mnop"
        assert "sk-12345" in result
        assert "mnop" in result

    def test_mask_exact_threshold(self):
        """Test masking when value equals threshold."""
        # With default show_prefix=8 and show_suffix=4, threshold is 12
        result = FieldEncryptionService.mask("123456789012", show_prefix=8, show_suffix=4)
        # Length equals threshold, should show masked
        assert result == "****"

    def test_mask_empty_value(self):
        """Test masking of empty value."""
        result = FieldEncryptionService.mask("")
        assert result == "****"

    def test_mask_with_different_parameters(self):
        """Test masking with custom prefix/suffix lengths."""
        api_key = "sk-1234567890abcdefghijklmnop"
        result = FieldEncryptionService.mask(api_key, show_prefix=5, show_suffix=3)
        assert result == "sk-12...nop"
        assert "sk-12" in result
        assert "nop" in result

    def test_mask_preserves_prefix_suffix_length(self):
        """Test that mask respects exact prefix/suffix lengths."""
        api_key = "sk-1234567890abcdefghijklmnop"

        # Test with show_prefix=10, show_suffix=6
        result = FieldEncryptionService.mask(api_key, show_prefix=10, show_suffix=6)
        assert result.startswith("sk-1234567...")
        assert result.endswith("klmnop")
        assert result == "sk-1234567...klmnop"
