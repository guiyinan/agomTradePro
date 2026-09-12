"""Real Token/HMAC requests and final credential checks on isolated PostgreSQL."""

import hashlib
import hmac
import time
from collections.abc import Iterator

import pytest
from django.db import connections
from django.test import Client, override_settings
from django.utils import timezone

from apps.account.infrastructure.identity_models import UserAccessTokenModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from core.integration import authenticated_canonical_account_creation as bridge
from tests.component.account import (
    test_account_actor_authority_raw_source_publisher_http as routing,
)
from tests.component.account.creation_chain_postgres_fixture import CREATION_LEDGER_MODELS
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)
from tests.component.account.test_authenticated_creation_http_postgres import (
    _post,
)
from tests.component.account.test_authenticated_creation_http_postgres import (
    creation_http_alias as creation_http_alias,
)

pytest_plugins = (
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
)

TEST_SECRET = "isolated-creation-http-test-secret"


@pytest.fixture
def credential_alias(creation_http_alias: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Add the actual token table and route backend queries to the disposable alias."""
    monkeypatch.setattr(
        routing,
        "_OWNED_MODEL_LABELS",
        routing._OWNED_MODEL_LABELS | {UserAccessTokenModel._meta.label_lower},
    )
    with connections[creation_http_alias].schema_editor() as editor:
        editor.create_model(UserAccessTokenModel)
    try:
        with override_settings(AGOMTRADEPRO_INTERNAL_AUTH_SECRET=TEST_SECRET):
            yield creation_http_alias
    finally:
        with connections[creation_http_alias].schema_editor() as editor:
            editor.delete_model(UserAccessTokenModel)


def _credential_client(alias: str, mode: str):
    user, profile = _new_user(alias)
    if mode == "token":
        raw = "local-test-creation-token"
        token = UserAccessTokenModel.objects.using(alias).create(
            user=user,
            key=UserAccessTokenModel.hash_key(raw),
            key_encrypted="",
            access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE,
        )
        client = Client(enforce_csrf_checks=True, HTTP_AUTHORIZATION=f"Token {raw}")
        return client, user, profile, token
    timestamp = str(int(time.time()))
    payload = ":".join([timestamp, "POST", "/api/account/accounts/", str(user.pk), user.username])
    signature = hmac.new(TEST_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    client = Client(
        enforce_csrf_checks=True,
        HTTP_X_AGOM_INTERNAL_SIGNATURE=signature,
        HTTP_X_AGOM_INTERNAL_TIMESTAMP=timestamp,
        HTTP_X_AGOM_INTERNAL_USER_ID=str(user.pk),
        HTTP_X_AGOM_INTERNAL_USERNAME=user.username,
    )
    return client, user, profile, None


def _assert_empty(alias: str) -> None:
    assert SimulatedAccountModel.objects.using(alias).count() == 0
    assert all(model.objects.using(alias).count() == 0 for model in CREATION_LEDGER_MODELS)


@pytest.mark.parametrize("mode", ["token", "internal"])
def test_real_credential_creates_replays_and_rejects_disabled_profile(
    credential_alias: str,
    mode: str,
) -> None:
    client, user, profile, _ = _credential_client(credential_alias, mode)
    first = _post(client, "")
    assert first.status_code == 201, first.content
    assert first["Content-Type"].startswith("application/json")
    replay = _post(client, "")
    assert replay.status_code == 200, replay.content
    assert replay.json()["replayed"] is True
    account_id = first.json()["account"]["account_id"]
    assert replay.json()["account"]["account_id"] == account_id
    assert (
        SimulatedAccountModel.objects.using(credential_alias).get(pk=account_id).user_id == user.pk
    )
    profile.mcp_enabled = False
    profile.save(using=credential_alias, update_fields=["mcp_enabled"])
    denied = _post(client, "", key="second", account_name="Second")
    assert denied.status_code in {401, 403}, denied.content
    assert SimulatedAccountModel.objects.using(credential_alias).count() == 1


@pytest.mark.parametrize("mode", ["token", "internal"])
def test_final_credential_recheck_rolls_back_entire_creation_graph(
    credential_alias: str,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, profile, token = _credential_client(credential_alias, mode)
    original = bridge.create_canonical_account
    observed = []

    def invalidate_after_creation(**kwargs):
        result = original(**kwargs)
        observed.append(SimulatedAccountModel.objects.using(credential_alias).count())
        if token is not None:
            UserAccessTokenModel.objects.using(credential_alias).filter(pk=token.pk).update(
                revoked_at=timezone.now(),
                is_active=False,
            )
        else:
            type(profile).objects.using(credential_alias).filter(pk=profile.pk).update(
                mcp_enabled=False
            )
        return result

    monkeypatch.setattr(bridge, "create_canonical_account", invalidate_after_creation)
    denied = _post(client, "")
    assert denied.status_code in {401, 403}, denied.content
    assert observed == [1], "must fail after the actual graph was written"
    _assert_empty(credential_alias)
    profile.refresh_from_db(using=credential_alias)
    assert profile.mcp_enabled is True
    if token is not None:
        token.refresh_from_db(using=credential_alias)
        assert token.is_active is True and token.revoked_at is None


def test_read_only_and_revoked_token_cannot_create(credential_alias: str) -> None:
    client, _, _, token = _credential_client(credential_alias, "token")
    assert token is not None
    token.access_level = UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY
    token.save(using=credential_alias, update_fields=["access_level"])
    denied = _post(client, "")
    assert denied.status_code == 403, denied.content
    token.access_level = UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE
    token.is_active = False
    token.revoked_at = timezone.now()
    token.save(using=credential_alias, update_fields=["access_level", "is_active", "revoked_at"])
    denied = _post(client, "")
    assert denied.status_code in {401, 403}, denied.content
    _assert_empty(credential_alias)
