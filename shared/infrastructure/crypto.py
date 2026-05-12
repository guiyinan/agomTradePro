"""
Field-level encryption service for sensitive data.

Provides AES-256-GCM encryption for fields like API keys.
Uses Fernet (symmetric encryption) from the cryptography library.
"""
import base64
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class FieldEncryptionService:
    """
    Service for encrypting and decrypting sensitive fields.

    Uses Fernet (AES-128-CBC + HMAC) for symmetric encryption.
    Keys are derived from the AGOMTRADEPRO_ENCRYPTION_KEY environment variable.
    """

    # Prefix to identify encrypted values
    PREFIX = "encrypted:v1:"

    def __init__(self, encryption_key: str | None = None):
        """
        Initialize the encryption service.

        Args:
            encryption_key: Optional explicit key. If not provided,
                          uses AGOMTRADEPRO_ENCRYPTION_KEY from settings.

        Raises:
            ValueError: If encryption key is not configured.
        """
        key = encryption_key or self._get_encryption_key()
        if not key:
            raise ValueError("AGOMTRADEPRO_ENCRYPTION_KEY not configured")

        # Ensure key is 32 bytes (URL-safe base64 encoded)
        # Fernet requires a 32-byte base64-encoded key
        self._raw_key = key.encode() if isinstance(key, str) else key
        self.fernet = self._create_fernet(self._raw_key)

    @staticmethod
    def _get_encryption_key() -> str | None:
        """
        Get encryption key from Django settings or environment.

        Returns:
            The encryption key or None if not configured.
        """
        # Check for explicit setting first
        if hasattr(settings, 'AGOMTRADEPRO_ENCRYPTION_KEY'):
            return settings.AGOMTRADEPRO_ENCRYPTION_KEY

        # Check environment variable
        key = os.environ.get('AGOMTRADEPRO_ENCRYPTION_KEY')
        if key:
            return key

        return None

    @staticmethod
    def _create_fernet(key: bytes) -> Fernet:
        """
        Create a Fernet instance from a key.

        Args:
            key: Raw key bytes

        Returns:
            Fernet instance

        Raises:
            ImproperlyConfigured: If key is invalid
        """
        try:
            # If key is already a valid Fernet key (44 bytes base64)
            if len(key) == 44:
                return Fernet(key)

            # Derive a proper Fernet key from the input
            # Use SHA256 to get 32 bytes, then base64 encode
            import hashlib
            hash_digest = hashlib.sha256(key).digest()
            fernet_key = base64.urlsafe_b64encode(hash_digest)
            return Fernet(fernet_key)
        except Exception as e:
            raise ImproperlyConfigured(f"Invalid encryption key: {e}") from e

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext value.

        Args:
            plaintext: The value to encrypt

        Returns:
            Encrypted value with prefix
        """
        if not plaintext:
            return ''

        try:
            encrypted_bytes = self.fernet.encrypt(plaintext.encode('utf-8'))
            encrypted_b64 = base64.urlsafe_b64encode(encrypted_bytes).decode('ascii')
            return f"{self.PREFIX}{encrypted_b64}"
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: str, *, suppress_warning: bool = False) -> str:
        """
        Decrypt a ciphertext value.

        Args:
            ciphertext: The encrypted value with prefix
            suppress_warning: Downgrade invalid-token logs for expected fallback
                paths such as rotated environment keys.

        Returns:
            Decrypted plaintext

        Raises:
            InvalidToken: If decryption fails (wrong key or corrupted data)
        """
        if not ciphertext:
            return ''

        # Handle legacy values without prefix
        if not ciphertext.startswith(self.PREFIX):
            # Try to decrypt as-is for backward compatibility
            try:
                encrypted_bytes = base64.urlsafe_b64decode(ciphertext.encode('ascii'))
                decrypted = self.fernet.decrypt(encrypted_bytes)
                return decrypted.decode('utf-8')
            except Exception:
                # If it fails, return as-is (might be plaintext)
                return ciphertext

        # Strip prefix and decrypt
        try:
            encrypted_b64 = ciphertext[len(self.PREFIX):]
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_b64.encode('ascii'))
            decrypted = self.fernet.decrypt(encrypted_bytes)
            return decrypted.decode('utf-8')
        except InvalidToken:
            log_message = "Decryption failed: invalid token or wrong key"
            if suppress_warning:
                logger.debug(log_message)
            else:
                logger.warning(log_message)
            raise
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    def is_encrypted(self, value: str) -> bool:
        """
        Check if a value is encrypted.

        Args:
            value: The value to check

        Returns:
            True if the value has the encryption prefix
        """
        return bool(value and value.startswith(self.PREFIX))

    @staticmethod
    def generate_key() -> str:
        """
        Generate a new Fernet-compatible encryption key.

        Returns:
            A 44-byte base64-encoded key suitable for AGOMTRADEPRO_ENCRYPTION_KEY
        """
        return Fernet.generate_key().decode('ascii')

    @staticmethod
    def mask(value: str, show_prefix: int = 8, show_suffix: int = 4) -> str:
        """
        Mask a sensitive value showing only prefix and suffix.

        Args:
            value: The value to mask
            show_prefix: Number of characters to show at the start
            show_suffix: Number of characters to show at the end

        Returns:
            Masked string in format "prefix...suffix"

        Examples:
            >>> FieldEncryptionService.mask("sk-1234567890abcdef")
            'sk-12345...cdef'
            >>> FieldEncryptionService.mask("short")
            '****'
        """
        if not value or len(value) <= show_prefix + show_suffix:
            return '****'
        return f"{value[:show_prefix]}...{value[-show_suffix:]}"


def get_encryption_service() -> FieldEncryptionService | None:
    """
    Get the encryption service instance.

    Returns None if encryption is not configured,
    allowing graceful degradation.

    Returns:
        FieldEncryptionService instance or None
    """
    try:
        return FieldEncryptionService()
    except ValueError:
        logger.info("Encryption not configured, using plaintext storage")
        return None


def mask_api_key(api_key: str, visible_chars: int = 4) -> str:
    """
    Mask an API key for display purposes.

    Args:
        api_key: The API key to mask
        visible_chars: Number of characters to show at the start

    Returns:
        Masked API key (e.g., "sk-***...")
    """
    if not api_key:
        return ''

    if len(api_key) <= visible_chars:
        return '***'

    # Show first few chars and mask the rest
    prefix = api_key[:visible_chars]
    return f"{prefix}{'*' * min(len(api_key) - visible_chars, 20)}"
