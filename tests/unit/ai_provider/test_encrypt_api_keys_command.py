"""Safety contracts for the AI provider API-key encryption command."""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.core.management.base import CommandError

from apps.ai_provider.infrastructure.management.commands.encrypt_api_keys import (
    Command,
)


def _command() -> tuple[Command, StringIO]:
    command = Command()
    output = StringIO()
    command.stdout = output
    return command, output


@pytest.mark.parametrize("service", [None, RuntimeError("key service failed")])
def test_command_fails_closed_when_encryption_service_is_unavailable(
    service: object,
) -> None:
    command, _output = _command()
    service_patch = (
        patch(
            "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys."
            "get_encryption_service",
            side_effect=service,
        )
        if isinstance(service, Exception)
        else patch(
            "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys."
            "get_encryption_service",
            return_value=service,
        )
    )

    with (
        service_patch,
        pytest.raises(
            CommandError,
            match="Encryption service not available|Failed to initialize encryption service",
        ),
    ):
        command.handle(dry_run=False, force=False)


def test_command_reports_noop_without_exposing_any_key_material() -> None:
    command, output = _command()
    queryset = Mock()
    queryset.filter.return_value = queryset
    queryset.count.return_value = 0

    with (
        patch(
            "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys."
            "get_encryption_service",
            return_value=Mock(),
        ),
        patch(
            "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys."
            "AIProviderConfig.objects.exclude",
            return_value=queryset,
        ) as exclude,
    ):
        command.handle(dry_run=False, force=False)

    exclude.assert_called_once_with(api_key="")
    queryset.filter.assert_called_once_with(api_key__isnull=False)
    assert output.getvalue().strip() == "No API keys found to encrypt."


def test_command_dry_run_summarizes_each_outcome_and_force_uses_all_rows() -> None:
    command, output = _command()
    providers = [SimpleNamespace(name=name) for name in ("one", "two", "three")]
    queryset = Mock()
    queryset.count.return_value = 3
    queryset.__iter__ = Mock(return_value=iter(providers))
    crypto = Mock()

    with (
        patch(
            "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys."
            "get_encryption_service",
            return_value=crypto,
        ),
        patch(
            "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys."
            "AIProviderConfig.objects.exclude"
        ),
        patch(
            "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys."
            "AIProviderConfig.objects.all",
            return_value=queryset,
        ) as all_rows,
        patch.object(
            command,
            "_encrypt_provider",
            side_effect=["encrypted", "skipped", "error"],
        ) as encrypt,
    ):
        command.handle(dry_run=True, force=True)

    all_rows.assert_called_once_with()
    assert encrypt.call_count == 3
    for call in encrypt.call_args_list:
        assert call.kwargs == {"dry_run": True, "force": True}
    text = output.getvalue()
    assert "Total providers: 3" in text
    assert "Encrypted: 1" in text
    assert "Skipped: 1" in text
    assert "Errors: 1" in text
    assert "Dry run complete. No changes were made." in text


def test_encrypt_provider_skips_existing_ciphertext_without_force() -> None:
    command, output = _command()
    provider = SimpleNamespace(
        name="configured",
        api_key="secret-value",
        api_key_encrypted="ciphertext",
        save=Mock(),
    )

    result = command._encrypt_provider(provider, Mock(), force=False)

    assert result == "skipped"
    assert "Already encrypted" in output.getvalue()
    assert "secret-value" not in output.getvalue()
    provider.save.assert_not_called()


def test_encrypt_provider_skips_missing_plaintext() -> None:
    command, output = _command()
    provider = SimpleNamespace(
        name="empty",
        api_key="",
        api_key_encrypted="",
        save=Mock(),
    )

    result = command._encrypt_provider(provider, Mock(), force=True)

    assert result == "skipped"
    assert "No plaintext API key" in output.getvalue()


def test_encrypt_provider_dry_run_masks_key_and_does_not_persist() -> None:
    command, output = _command()
    provider = SimpleNamespace(
        name="dry-run",
        api_key="abcdefgh-super-secret",
        api_key_encrypted="",
        save=Mock(),
    )
    crypto = Mock()

    result = command._encrypt_provider(provider, crypto, dry_run=True)

    assert result == "encrypted"
    assert "Encrypting: ***" in output.getvalue()
    assert "super-secret" not in output.getvalue()
    crypto.encrypt.assert_not_called()
    provider.save.assert_not_called()


def test_encrypt_provider_persists_ciphertext_and_clears_plaintext_atomically() -> None:
    command, output = _command()
    provider = SimpleNamespace(
        name="live",
        api_key="plain-secret",
        api_key_encrypted="",
        save=Mock(),
    )
    crypto = Mock()
    crypto.encrypt.return_value = "ciphertext"
    atomic = Mock()
    atomic.return_value.__enter__ = Mock()
    atomic.return_value.__exit__ = Mock(return_value=False)

    with patch(
        "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys."
        "transaction.atomic",
        atomic,
    ):
        result = command._encrypt_provider(provider, crypto)

    assert result == "encrypted"
    crypto.encrypt.assert_called_once_with("plain-secret")
    assert provider.api_key_encrypted == "ciphertext"
    assert provider.api_key == ""
    provider.save.assert_called_once_with(update_fields=["api_key_encrypted", "api_key"])
    assert "plain-secret" not in output.getvalue()


def test_encrypt_provider_contains_failure_and_never_prints_plaintext() -> None:
    command, output = _command()
    provider = SimpleNamespace(
        name="failed",
        api_key="abcdefgh-secret",
        api_key_encrypted="",
        save=Mock(),
    )
    crypto = Mock()
    crypto.encrypt.side_effect = RuntimeError("vault offline")
    atomic = Mock()
    atomic.return_value.__enter__ = Mock()
    atomic.return_value.__exit__ = Mock(return_value=False)

    with patch(
        "apps.ai_provider.infrastructure.management.commands.encrypt_api_keys."
        "transaction.atomic",
        atomic,
    ):
        result = command._encrypt_provider(provider, crypto)

    assert result == "error"
    assert "Error (RuntimeError)" in output.getvalue()
    assert "vault offline" not in output.getvalue()
    assert "abcdefgh-secret" not in output.getvalue()


@pytest.mark.parametrize(
    ("api_key", "expected"),
    [
        ("", "(empty)"),
        ("short", "***"),
        ("abcdefgh1234", "***"),
    ],
)
def test_mask_key_never_returns_complete_secret(api_key: str, expected: str) -> None:
    assert Command._mask_key(api_key) == expected
