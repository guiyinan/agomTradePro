"""
Field-level encryption service for sensitive data.

Provides authenticated Fernet encryption for fields like API keys.
Fernet uses AES-128-CBC with HMAC-SHA256 authentication.
"""

import base64
import hashlib
import logging
import os

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

    @staticmethod
    def _require_bytes(value: object, *, operation: str) -> bytes:
        """Narrow cryptography's dynamic return values at the library boundary."""

        if not isinstance(value, bytes):
            raise TypeError(f"{operation} must return bytes")
        return value

    def __init__(self, encryption_key: str | None = None) -> None:
        """
        Initialize the encryption service.

        Args:
            encryption_key: Optional explicit key. If not provided,
                          uses AGOMTRADEPRO_ENCRYPTION_KEY from settings.

        Raises:
            ValueError: If encryption key is not configured.
        """
        key = encryption_key if encryption_key is not None else self._get_encryption_key()
        if not isinstance(key, str) or not key.strip():
            raise ValueError("AGOMTRADEPRO_ENCRYPTION_KEY not configured")
        key = key.strip()

        self._raw_key = key.encode("utf-8")
        self.fernet = self._create_fernet(self._raw_key)

    @staticmethod
    def _get_encryption_key() -> str | None:
        """
        Get encryption key from Django settings or environment.

        Returns:
            The encryption key or None if not configured.
        """
        configured_key = getattr(settings, "AGOMTRADEPRO_ENCRYPTION_KEY", None)
        if configured_key is not None:
            if not isinstance(configured_key, str):
                raise ImproperlyConfigured("AGOMTRADEPRO_ENCRYPTION_KEY must be a string")
            return configured_key.strip() or None

        environment_key = os.environ.get("AGOMTRADEPRO_ENCRYPTION_KEY")
        if environment_key:
            return environment_key.strip() or None

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

            # Preserve the legacy deterministic derivation used by existing data.
            hash_digest = hashlib.sha256(key).digest()
            fernet_key = base64.urlsafe_b64encode(hash_digest)
            return Fernet(fernet_key)
        except Exception as exc:
            raise ImproperlyConfigured("Invalid encryption key format") from exc

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext value.

        Args:
            plaintext: The value to encrypt

        Returns:
            Encrypted value with prefix
        """
        if not plaintext:
            return ""

        try:
            encrypted_bytes = self._require_bytes(
                self.fernet.encrypt(plaintext.encode("utf-8")),
                operation="Fernet encryption",
            )
            encrypted_b64 = base64.urlsafe_b64encode(encrypted_bytes).decode("ascii")
            return f"{self.PREFIX}{encrypted_b64}"
        except Exception as exc:
            logger.error(
                "Field encryption failed",
                extra={"exception_type": type(exc).__name__},
            )
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
            return ""

        # Handle legacy values without prefix
        if not ciphertext.startswith(self.PREFIX):
            # Try to decrypt as-is for backward compatibility
            try:
                encrypted_bytes = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
                decrypted = self._require_bytes(
                    self.fernet.decrypt(encrypted_bytes),
                    operation="Fernet decryption",
                )
                return decrypted.decode("utf-8")
            except Exception:
                # If it fails, return as-is (might be plaintext)
                return ciphertext

        # Strip prefix and decrypt
        try:
            encrypted_b64 = ciphertext[len(self.PREFIX) :]
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_b64.encode("ascii"))
            decrypted = self._require_bytes(
                self.fernet.decrypt(encrypted_bytes),
                operation="Fernet decryption",
            )
            return decrypted.decode("utf-8")
        except InvalidToken:
            log_message = "Decryption failed: invalid token or wrong key"
            if suppress_warning:
                logger.debug(log_message)
            else:
                logger.warning(log_message)
            raise
        except Exception as exc:
            logger.error(
                "Field decryption failed",
                extra={"exception_type": type(exc).__name__},
            )
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
        generated = FieldEncryptionService._require_bytes(
            Fernet.generate_key(),
            operation="Fernet key generation",
        )
        return generated.decode("ascii")

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
        if isinstance(show_prefix, bool) or not isinstance(show_prefix, int) or show_prefix < 0:
            raise ValueError("show_prefix must be a non-negative integer")
        if isinstance(show_suffix, bool) or not isinstance(show_suffix, int) or show_suffix < 0:
            raise ValueError("show_suffix must be a non-negative integer")
        if not value or show_prefix + show_suffix == 0 or len(value) <= show_prefix + show_suffix:
            return "****"
        visible_prefix = value[:show_prefix] if show_prefix else ""
        visible_suffix = value[-show_suffix:] if show_suffix else ""
        return f"{visible_prefix}...{visible_suffix}"


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


def mask_api_key(api_key: str | None, visible_chars: int = 4) -> str:
    """
    Mask an API key for display purposes.

    Args:
        api_key: The API key to mask
        visible_chars: Number of characters to show at the start

    Returns:
        Masked API key (e.g., "sk-***...")
    """
    if not api_key:
        return ""
    if isinstance(visible_chars, bool) or not isinstance(visible_chars, int) or visible_chars < 0:
        raise ValueError("visible_chars must be a non-negative integer")

    if len(api_key) <= visible_chars:
        return "***"

    # Show first few chars and mask the rest
    prefix = api_key[:visible_chars]
    return f"{prefix}{'*' * min(len(api_key) - visible_chars, 20)}"
