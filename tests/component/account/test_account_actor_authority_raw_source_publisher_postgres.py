"""Opt-in PostgreSQL and rollback tests for the authenticated Account publisher."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from urllib.parse import unquote, urlsplit

import pytest
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import connections, models
from django.utils.crypto import get_random_string

from apps.account import account_actor_authority_capture_composition as composition
from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_actor_authority_raw_source_publisher_v3 import (
    DjangoAccountActorAuthorityRawSourcePublisherGatewayV3,
)
from apps.account.infrastructure.account_authentication_context_source_v3_repository import (
    DjangoAccountAuthenticationContextSourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_rbac_authority_source_v3_repository import (
    DjangoAccountRbacAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_user_authority_source_v3_repository import (
    DjangoAccountUserAuthoritySourceV3Repository,
)
from apps.account.infrastructure.identity_models import AccountProfileModel

PG_ALIAS = "evid06_authority_test"
_MODELS: tuple[type[models.Model], ...] = (
    ContentType,
    Permission,
    Group,
    User,
    Session,
    AccountProfileModel,
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)


class _DjangoDbBlocker(Protocol):
    def unblock(self) -> AbstractContextManager[None]:
        """Allow the fixture to create its isolated schema."""


@dataclass(frozen=True, slots=True)
class _RequestSession:
    """Minimal request-session view carrying no database credentials."""

    session_key: str
    values: dict[str, object]

    def get(self, key: str, default: object = None) -> object:
        """Return one decoded request value."""

        return self.values.get(key, default)


@pytest.fixture(name="evid06_alias")
def evid06_alias(
    django_db_blocker: _DjangoDbBlocker, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """Create the dedicated loopback PostgreSQL schema only when explicitly enabled."""

    if os.environ.get("AGOM_EVID06_POSTGRES_TEST") != "1":
        pytest.skip("set AGOM_EVID06_POSTGRES_TEST=1 for the disposable EVID-06 test")
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    database_url = os.environ.get("AGOM_EVID06_POSTGRES_TEST_DATABASE_URL", "").strip()
    parsed = urlsplit(database_url)
    database_name = unquote(parsed.path.removeprefix("/"))
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("EVID-06 PostgreSQL tests require a PostgreSQL URL")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("EVID-06 PostgreSQL tests require a loopback host")
    if database_name != "evid06_authority_test" or not parsed.username:
        raise RuntimeError("EVID-06 PostgreSQL tests require the dedicated test database")
    if PG_ALIAS in connections.databases:
        raise RuntimeError(f"refusing preexisting database alias: {PG_ALIAS}")
    try:
        port = parsed.port
    except ValueError as error:
        raise RuntimeError("EVID-06 PostgreSQL test URL has an invalid port") from error
    database_settings = cast(dict[str, object], deepcopy(connections["default"].settings_dict))
    database_settings.update(
        {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": database_name,
            "USER": unquote(parsed.username),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname,
            "PORT": str(port or 5432),
            "CONN_MAX_AGE": 0,
            "OPTIONS": {},
        }
    )
    connections.databases[PG_ALIAS] = database_settings  # type: ignore[assignment]
    connection = connections[PG_ALIAS]
    created: list[type[models.Model]] = []
    try:
        with django_db_blocker.unblock():
            try:
                if connection.introspection.table_names():
                    raise RuntimeError("refusing a non-empty dedicated EVID-06 database")
                with connection.schema_editor() as editor:
                    for model in _MODELS:
                        editor.create_model(model)
                        created.append(model)
                yield PG_ALIAS
            finally:
                if created:
                    with connection.schema_editor() as editor:
                        for model in reversed(created):
                            editor.delete_model(model)
    finally:
        connection.close()
        connections.databases.pop(PG_ALIAS, None)


def _session_for_user(alias: str, user: User, *, expires_at: datetime) -> _RequestSession:
    """Persist one real Django session row and return its request-side decoded view."""

    backend = cast(tuple[str, ...], tuple(settings.AUTHENTICATION_BACKENDS))[0]
    values: dict[str, object] = {
        SESSION_KEY: str(user.pk),
        BACKEND_SESSION_KEY: backend,
        HASH_SESSION_KEY: user.get_session_auth_hash(),
    }
    store = SessionStore()
    session_key = f"evid06{get_random_string(26)}"
    Session._default_manager.using(alias).create(
        session_key=session_key,
        session_data=store.encode(values),
        expire_date=expires_at,
    )
    return _RequestSession(session_key=session_key, values=values)


def _new_user(alias: str, *, username: str = "evid06-owner") -> tuple[User, AccountProfileModel]:
    """Create the owner-like superuser fixture without changing any existing account."""

    user = User(
        username=username,
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )
    user.set_password("evid06-test-password")
    user.save(using=alias)
    profile = AccountProfileModel(
        user=user,
        display_name="EVID06 owner",
        rbac_role="owner",
        mcp_enabled=True,
        approval_status="pending",
    )
    profile.save(using=alias)
    return user, profile


def _gateway(alias: str, user: User, session: _RequestSession):
    """Build one gateway bound to the fresh user and the dedicated alias."""

    bound_user = User._default_manager.using(alias).get(pk=user.pk)
    return DjangoAccountActorAuthorityRawSourcePublisherGatewayV3(
        authenticated_user=bound_user,
        session=session,
        using=alias,
    )


def _raw_counts(alias: str) -> tuple[int, ...]:
    """Return all eight append-only raw/actor row counts."""

    return tuple(model._default_manager.using(alias).count() for model in _MODELS[6:])


def test_authenticated_session_publishes_four_exact_sources_without_mutation(
    evid06_alias: str,
) -> None:
    """A real session produces roots and actor evidence with effective admin RBAC."""

    user, profile = _new_user(evid06_alias)
    profile_before = (profile.rbac_role, profile.approval_status, profile.approved_by_id)
    expires_at = datetime.now(UTC) + timedelta(minutes=20)
    session = _session_for_user(evid06_alias, user, expires_at=expires_at)

    receipt = _gateway(evid06_alias, user, session).publish()
    payload = receipt.to_payload()

    assert payload["outcome"] == "success"
    assert payload["status"] == "attestation_only"
    assert payload["user_id"] == user.pk
    assert payload["principal_id"].startswith("django-session-principal-v3:")
    assert _raw_counts(evid06_alias) == (1,) * 8
    assert payload["authentication_context"]["source_version"] == "v1"
    assert payload["actor"]["source_version"] == "v1"
    assert "session_key" not in str(payload)
    assert "password" not in str(payload)
    assert "scope" not in payload
    assert "approval" not in payload

    profile.refresh_from_db(using=evid06_alias)
    assert (profile.rbac_role, profile.approval_status, profile.approved_by_id) == profile_before
    stored_session = Session._default_manager.using(evid06_alias).get(
        session_key=session.session_key
    )
    assert stored_session.expire_date == expires_at
    assert stored_session.expire_date >= receipt.valid_until

    actor_selector = payload["actor"]
    authentication_selector = payload["authentication_context"]
    assert isinstance(actor_selector, dict)
    assert isinstance(authentication_selector, dict)
    reader = composition.build_account_actor_authority_request_reader(
        source_id=cast(str, actor_selector["source_id"]),
        source_version=cast(str, actor_selector["source_version"]),
        expected_content_hash=cast(str, actor_selector["content_hash"]),
        using=evid06_alias,
    )
    current = reader.get_exact_current(
        principal_id=receipt.principal_id,
        user_id=receipt.user_id,
        expected_authentication_context_hash=cast(str, authentication_selector["content_hash"]),
        as_of=datetime.now(UTC),
    )
    assert current is not None
    assert current.source_id == receipt.actor.source_id
    assert current.source_content_hash == receipt.actor.content_hash
    assert current.authentication_context_hash == receipt.authentication_context.content_hash


def test_invalid_session_fails_before_any_raw_write(evid06_alias: str) -> None:
    """An expired database session cannot be converted into current evidence."""

    user, _ = _new_user(evid06_alias)
    session = _session_for_user(
        evid06_alias,
        user,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable):
        _gateway(evid06_alias, user, session).publish()
    assert _raw_counts(evid06_alias) == (0,) * 8


@pytest.mark.parametrize("tamper", ["deleted", "inactive", "stale_hash", "wrong_user"])
def test_session_and_user_binding_fail_closed_before_any_raw_write(
    evid06_alias: str, tamper: str
) -> None:
    """Reject a missing, inactive, stale, or cross-user session before appends."""

    user, _ = _new_user(evid06_alias)
    session = _session_for_user(
        evid06_alias,
        user,
        expires_at=datetime.now(UTC) + timedelta(minutes=20),
    )
    authenticated_user = user
    if tamper == "deleted":
        Session._default_manager.using(evid06_alias).filter(
            session_key=session.session_key
        ).delete()
    elif tamper == "inactive":
        user.is_active = False
        user.save(using=evid06_alias, update_fields=["is_active"])
    elif tamper == "stale_hash":
        user.set_password("evid06-new-test-password")
        user.save(using=evid06_alias, update_fields=["password"])
    else:
        authenticated_user, _ = _new_user(evid06_alias, username="evid06-other-owner")

    with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable):
        _gateway(evid06_alias, authenticated_user, session).publish()
    assert _raw_counts(evid06_alias) == (0,) * 8


def test_user_loaded_on_another_alias_is_rejected_before_any_raw_write(
    evid06_alias: str,
) -> None:
    """A PostgreSQL request cannot publish through an alias unlike its User row."""

    user, _ = _new_user(evid06_alias)
    session = _session_for_user(
        evid06_alias,
        user,
        expires_at=datetime.now(UTC) + timedelta(minutes=20),
    )
    wrong_alias = "evid06_wrong_alias"
    connections.databases[wrong_alias] = deepcopy(
        connections[evid06_alias].settings_dict
    )  # type: ignore[assignment]
    bound_user = User._default_manager.using(evid06_alias).get(pk=user.pk)
    try:
        with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable):
            DjangoAccountActorAuthorityRawSourcePublisherGatewayV3(
                authenticated_user=bound_user,
                session=session,
                using=wrong_alias,
            ).publish()
    finally:
        connections[wrong_alias].close()
        connections.databases.pop(wrong_alias, None)
    assert _raw_counts(evid06_alias) == (0,) * 8


@pytest.mark.parametrize(
    "repository_type",
    [
        pytest.param(
            DjangoAccountAuthenticationContextSourceV3Repository,
            id="authentication-raw-append",
        ),
        pytest.param(
            DjangoAccountUserAuthoritySourceV3Repository,
            id="user-raw-append",
        ),
        pytest.param(
            DjangoAccountRbacAuthoritySourceV3Repository,
            id="rbac-raw-append",
        ),
        pytest.param(
            DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
            id="actor-append",
        ),
    ],
)
def test_failure_after_any_append_rolls_back_all_eight_rows(
    evid06_alias: str,
    monkeypatch: pytest.MonkeyPatch,
    repository_type: type[object],
) -> None:
    """An exception after any raw or actor append cannot leave a partial graph."""

    user, _ = _new_user(evid06_alias)
    session = _session_for_user(
        evid06_alias,
        user,
        expires_at=datetime.now(UTC) + timedelta(minutes=20),
    )
    original_append = repository_type.append  # type: ignore[attr-defined]

    def fail_after_append(repository: object, *args: object, **kwargs: object) -> object:
        """Persist one append, then inject a failure inside the outer transaction."""

        original_append(repository, *args, **kwargs)  # type: ignore[operator]
        raise RuntimeError("test failure after append")

    monkeypatch.setattr(repository_type, "append", fail_after_append)
    with pytest.raises(RuntimeError, match="test failure after append"):
        _gateway(evid06_alias, user, session).publish()
    assert _raw_counts(evid06_alias) == (0,) * 8


def test_actor_capture_failure_rolls_back_all_four_ledgers(
    evid06_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after the raw roots are appended leaves no partial authority graph."""

    user, _ = _new_user(evid06_alias)
    session = _session_for_user(
        evid06_alias,
        user,
        expires_at=datetime.now(UTC) + timedelta(minutes=20),
    )

    def fail_capture(**kwargs: object) -> object:
        """Inject a failure at the derived actor source boundary."""

        del kwargs
        raise RuntimeError("test actor capture failure")

    import apps.account.infrastructure.account_actor_authority_raw_source_publisher_v3 as publisher_module

    monkeypatch.setattr(publisher_module, "build_account_actor_authority_capture", fail_capture)
    with pytest.raises(RuntimeError, match="test actor capture failure"):
        _gateway(evid06_alias, user, session).publish()
    assert _raw_counts(evid06_alias) == (0,) * 8
