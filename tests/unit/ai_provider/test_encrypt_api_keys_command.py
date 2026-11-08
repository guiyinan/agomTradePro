"""Compatibility contracts for the retired plaintext-key migration command."""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"dry_run": True},
        {"force": True},
        {"dry_run": True, "force": True},
    ],
)
def test_retired_command_fails_closed_for_legacy_invocations_without_db_or_crypto(
    options: dict[str, bool],
) -> None:
    """Historical flags parse, then the retired command refuses all work."""

    with (
        patch("django.db.connection.cursor", side_effect=AssertionError("database access")),
        patch(
            "shared.infrastructure.crypto.get_encryption_service",
            side_effect=AssertionError("encryption access"),
        ),
        pytest.raises(CommandError, match="encrypt_api_keys is retired"),
    ):
        call_command("encrypt_api_keys", **options)


def test_django_cli_reports_nonzero_for_retired_command_and_keeps_flags() -> None:
    """The standard app command shim retains its name and exits through CommandError."""

    command = load_command_class("apps.ai_provider", "encrypt_api_keys")
    assert command.requires_system_checks == []
    stderr = StringIO()
    command.stderr = stderr

    with patch("django.db.connection.cursor", side_effect=AssertionError("database access")):
        with pytest.raises(SystemExit) as exit_info:
            command.run_from_argv(["manage.py", "encrypt_api_keys", "--dry-run", "--force"])

    assert exit_info.value.code == 1
    assert "encrypt_api_keys is retired" in stderr.getvalue()
