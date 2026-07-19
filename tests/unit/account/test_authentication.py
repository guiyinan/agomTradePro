import hashlib
import hmac
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import exceptions
from rest_framework.test import APIRequestFactory

from apps.account.infrastructure.models import AccountProfileModel, UserAccessTokenModel
from apps.account.interface.authentication import (
    MultiTokenAuthentication,
    TerminalInternalAuthentication,
)


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

    authenticated_user, authenticated_token = MultiTokenAuthentication().authenticate_credentials(
        raw_key
    )

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


@pytest.mark.django_db
def test_multi_token_authentication_allows_explicit_pure_compute_post() -> None:
    """A read-only token may call a POST action explicitly classified as read-only."""
    user = get_user_model().objects.create_user(
        username=f"token_readonly_compute_{uuid.uuid4().hex[:8]}",
        password="test-pass-123",
    )
    _create_profile(user, mcp_enabled=True)
    _, raw_key = UserAccessTokenModel.create_token(
        user=user,
        name="readonly-sdk",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    request = APIRequestFactory().post(
        "/api/regime/calculate/",
        HTTP_AUTHORIZATION=f"Token {raw_key}",
    )
    request.parser_context = {
        "view": SimpleNamespace(
            action="calculate",
            read_only_actions=frozenset({"calculate"}),
        )
    }

    authenticated_user, authenticated_token = MultiTokenAuthentication().authenticate(request)

    assert authenticated_user.id == user.id
    assert authenticated_token.access_level == UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY


def _internal_signature(
    *, secret: str, timestamp: str, method: str, path: str, user_id: int, username: str
) -> str:
    payload = TerminalInternalAuthentication._build_signature_payload(
        timestamp=timestamp,
        method=method,
        path=path,
        user_id=str(user_id),
        username=username,
    )
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_INTERNAL_AUTH_SECRET="terminal-secret")
def test_terminal_internal_authentication_returns_originating_user():
    user = get_user_model().objects.create_user(
        username=f"terminal_user_{uuid.uuid4().hex[:8]}",
        password="test-pass-123",
    )
    request = APIRequestFactory().get(
        "/api/regime/current/?scope=latest",
        HTTP_X_AGOM_INTERNAL_TIMESTAMP="1700000000",
        HTTP_X_AGOM_INTERNAL_USER_ID=str(user.id),
        HTTP_X_AGOM_INTERNAL_USERNAME=user.username,
        HTTP_X_AGOM_INTERNAL_SIGNATURE=_internal_signature(
            secret="terminal-secret",
            timestamp="1700000000",
            method="GET",
            path="/api/regime/current/?scope=latest",
            user_id=user.id,
            username=user.username,
        ),
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("apps.account.interface.authentication.time.time", lambda: 1700000000)
        authenticated_user, _ = TerminalInternalAuthentication().authenticate(request)

    assert authenticated_user.id == user.id


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_INTERNAL_AUTH_SECRET="terminal-secret")
def test_terminal_internal_authentication_rejects_invalid_signature():
    user = get_user_model().objects.create_user(
        username=f"terminal_bad_{uuid.uuid4().hex[:8]}",
        password="test-pass-123",
    )
    request = APIRequestFactory().get(
        "/api/regime/current/",
        HTTP_X_AGOM_INTERNAL_TIMESTAMP="1700000000",
        HTTP_X_AGOM_INTERNAL_USER_ID=str(user.id),
        HTTP_X_AGOM_INTERNAL_USERNAME=user.username,
        HTTP_X_AGOM_INTERNAL_SIGNATURE="bad-signature",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("apps.account.interface.authentication.time.time", lambda: 1700000000)
        with pytest.raises(
            exceptions.AuthenticationFailed, match="Invalid internal auth signature"
        ):
            TerminalInternalAuthentication().authenticate(request)
