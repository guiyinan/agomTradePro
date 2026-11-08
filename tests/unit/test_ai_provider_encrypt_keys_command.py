"""The old migration command remains discoverable but can no longer mutate data."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_encrypt_api_keys_command_retirement_message_is_stable() -> None:
    with pytest.raises(CommandError) as exc_info:
        call_command("encrypt_api_keys", dry_run=True)

    message = str(exc_info.value)
    assert message.startswith("encrypt_api_keys is retired")
    assert "guarded ai_provider schema migration" in message
