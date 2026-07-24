from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.account.infrastructure.models import UserAccessTokenModel


@pytest.mark.django_db
def test_encryption_readiness_command_accepts_recoverable_tokens(admin_user):
    UserAccessTokenModel.create_token(
        user=admin_user,
        name="readiness-ok",
        created_by=admin_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    output = StringIO()

    call_command("check_encryption_readiness", "--json", stdout=output)

    assert '"status": "ready"' in output.getvalue()
    assert '"recoverable_token_count": 1' in output.getvalue()


@pytest.mark.django_db
def test_encryption_readiness_command_rejects_key_mismatch(admin_user):
    token, _ = UserAccessTokenModel.create_token(
        user=admin_user,
        name="readiness-blocked",
        created_by=admin_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    token.key_encrypted = "invalid-ciphertext"
    token.save(update_fields=["key_encrypted", "updated_at"])
    output = StringIO()

    with pytest.raises(CommandError, match="does not match"):
        call_command("check_encryption_readiness", "--json", stdout=output)

    assert '"status": "blocked"' in output.getvalue()
    assert "active MCP token ciphertext cannot be decrypted" in output.getvalue()
