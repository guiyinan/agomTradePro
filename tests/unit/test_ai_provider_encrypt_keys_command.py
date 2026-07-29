"""AI-provider key-encryption command boundary tests."""

from contextlib import nullcontext
from io import StringIO
from types import SimpleNamespace

from apps.ai_provider.infrastructure.management.commands.encrypt_api_keys import Command
from shared.infrastructure.crypto import FieldEncryptionService


class _FakeEncryptionService:
    def encrypt(self, plaintext: str) -> str:
        return f"{FieldEncryptionService.PREFIX}ciphertext"

    def is_encrypted(self, value: str) -> bool:
        return value.startswith(FieldEncryptionService.PREFIX)


def test_encrypt_provider_clears_plaintext_without_printing_key_prefix(monkeypatch) -> None:
    """Successful migration persists only ciphertext and fully masks operator output."""

    provider = SimpleNamespace(
        name="primary",
        api_key="sk-super-secret-value",
        api_key_encrypted="",
        save=lambda **kwargs: None,
    )
    output = StringIO()
    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys.transaction.atomic",
        nullcontext,
    )

    result = Command(stdout=output)._encrypt_provider(
        provider,
        _FakeEncryptionService(),
    )

    assert result == "encrypted"
    assert provider.api_key == ""
    assert provider.api_key_encrypted.startswith(FieldEncryptionService.PREFIX)
    assert "sk-super" not in output.getvalue()


def test_encrypt_provider_redacts_encryption_exception_message() -> None:
    """Encryption failures expose only their class, never embedded key material."""

    secret = "postgresql://user:secret@database.internal/runtime"

    class _FailingEncryptionService(_FakeEncryptionService):
        def encrypt(self, plaintext: str) -> str:
            raise RuntimeError(secret)

    provider = SimpleNamespace(
        name="primary",
        api_key="sk-super-secret-value",
        api_key_encrypted="",
        save=lambda **kwargs: None,
    )
    output = StringIO()

    result = Command(stdout=output)._encrypt_provider(
        provider,
        _FailingEncryptionService(),
    )

    assert result == "error"
    assert secret not in output.getvalue()
    assert "RuntimeError" in output.getvalue()
