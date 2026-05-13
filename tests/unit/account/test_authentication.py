import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import exceptions
from rest_framework.test import APIRequestFactory

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


@pytest.mark.django_db
def test_multi_token_authentication_rejects_write_with_read_only_token():
    user = get_user_model().objects.create_user(
        username=f"token_readonly_{uuid.uuid4().hex[:8]}",
        password="test-pass-123",
    )
    _create_profile(user, mcp_enabled=True)
    _, raw_key = UserAccessTokenModel.create_token(
        user=user,
        name="readonly-sdk",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    request = APIRequestFactory().post(
        "/api/system/config-center/qlib/runtime/",
        HTTP_AUTHORIZATION=f"Token {raw_key}",
    )

    with pytest.raises(exceptions.PermissionDenied, match="read-only"):
        MultiTokenAuthentication().authenticate(request)


@pytest.mark.django_db
def test_multi_token_authentication_allows_safe_read_with_read_only_token():
    user = get_user_model().objects.create_user(
        username=f"token_readonly_get_{uuid.uuid4().hex[:8]}",
        password="test-pass-123",
    )
    _create_profile(user, mcp_enabled=True)
    token, raw_key = UserAccessTokenModel.create_token(
        user=user,
        name="readonly-sdk",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    request = APIRequestFactory().get(
        "/api/system/config-center/qlib/runtime/",
        HTTP_AUTHORIZATION=f"Token {raw_key}",
    )

    authenticated_user, authenticated_token = MultiTokenAuthentication().authenticate(request)

    token.refresh_from_db()
    assert authenticated_user.id == user.id
    assert authenticated_token.id == token.id
    assert authenticated_token.access_level == UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY
