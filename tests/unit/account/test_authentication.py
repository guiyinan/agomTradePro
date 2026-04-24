import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import exceptions

from apps.account.infrastructure.models import AccountProfileModel, UserAccessTokenModel
from apps.account.interface.authentication import MultiTokenAuthentication


def _create_profile(user, *, mcp_enabled: bool = True) -> None:
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": user.username,
            "initial_capital": Decimal("1000000.00"),
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
            "mcp_enabled": mcp_enabled,
        },
    )


@pytest.mark.django_db
def test_multi_token_authentication_returns_user_and_updates_last_used():
    user = get_user_model().objects.create_user(
        username=f"token_user_{uuid.uuid4().hex[:8]}",
        password="test-pass-123",
    )
    _create_profile(user, mcp_enabled=True)
    token, raw_key = UserAccessTokenModel.create_token(user=user, name="desktop")

    authenticated_user, authenticated_token = MultiTokenAuthentication().authenticate_credentials(raw_key)

    token.refresh_from_db()
    assert authenticated_user.id == user.id
    assert authenticated_token.id == token.id
    assert token.last_used_at is not None


@pytest.mark.django_db
def test_multi_token_authentication_rejects_disabled_mcp_profile():
    user = get_user_model().objects.create_user(
        username=f"token_blocked_{uuid.uuid4().hex[:8]}",
        password="test-pass-123",
    )
    _create_profile(user, mcp_enabled=False)
    token, raw_key = UserAccessTokenModel.create_token(user=user, name="desktop")

    with pytest.raises(exceptions.AuthenticationFailed, match="MCP access disabled."):
        MultiTokenAuthentication().authenticate_credentials(raw_key)

    token.refresh_from_db()
    assert token.last_used_at is None
