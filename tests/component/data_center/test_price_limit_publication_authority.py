"""Real-session tests for the dedicated price-limit publication permission."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
    get_user_model,
)
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connection, connections, models, transaction
from django.test import override_settings
from django.utils import timezone

from apps.data_center.application.price_limit_publication_authority import (
    PriceLimitPublisherSessionRequestProof,
)
from apps.data_center.infrastructure.price_limit_publication_authority_repository import (
    DjangoPriceLimitPublisherAuthorityRepository,
)
from core.exceptions import AuthorizationError
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()
_PRICE_LIMIT_PERMISSION = "publish_price_limit"
_CALENDAR_PUBLISH_PERMISSION = "publish_exchange_calendar"
_CALENDAR_AUDIT_PERMISSION = "view_exchange_calendar_publication_audit"


@pytest.fixture(autouse=True)
def _auth_schema(
    django_db_blocker: object,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Build only auth/session tables and suppress unrelated user signals."""

    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    model_types = (ContentType, Permission, Group, User, Session)
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(model_types):
            try:
                yield
            finally:
                User.user_permissions.through.objects.all().delete()
                User.groups.through.objects.all().delete()
                Group.permissions.through.objects.all().delete()


def _permission(content_model: str, codename: str) -> Permission:
    """Create one exact permission definition for a test-only content type."""

    content_type, _ = ContentType.objects.get_or_create(
        app_label="data_center",
        model=content_model,
    )
    if content_type.app_label != "data_center" or content_type.model != content_model:
        raise AssertionError("Existing content type does not match the requested model")
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename=codename,
        defaults={"name": f"Can {codename.replace('_', ' ')}"},
    )
    if permission.content_type_id != content_type.pk or permission.codename != codename:
        raise AssertionError("Existing permission does not match its fixed authority purpose")
    return permission


@pytest.fixture
def price_limit_permission() -> Permission:
    """Return the dedicated price-limit fact permission, separate from Calendar."""

    return _permission("pricelimitsnapshotfactmodel", _PRICE_LIMIT_PERMISSION)


def _new_user(
    username: str,
    *,
    is_staff: bool = False,
    is_superuser: bool = False,
) -> Any:
    """Create an active user without granting implicit publisher authority."""

    return User.objects.create_user(
        username=username,
        password="test-only-price-limit-password",
        is_active=True,
        is_staff=is_staff,
        is_superuser=is_superuser,
    )


def _proof_for_user(user: Any) -> PriceLimitPublisherSessionRequestProof:
    """Persist a real session that the repository can reload under lock."""

    now = timezone.now()
    session_key = f"{int(user.pk):040d}"
    Session.objects.create(
        session_key=session_key,
        session_data=SessionStore().encode(
            {
                SESSION_KEY: str(user.pk),
                BACKEND_SESSION_KEY: settings.AUTHENTICATION_BACKENDS[0],
                HASH_SESSION_KEY: user.get_session_auth_hash(),
            }
        ),
        expire_date=now + timedelta(minutes=5),
    )
    return PriceLimitPublisherSessionRequestProof(
        user_id=int(user.pk),
        session_key=session_key,
        request_authenticated_at=now,
        request_user_database_alias=DEFAULT_DB_ALIAS,
        database_alias=DEFAULT_DB_ALIAS,
    )


def _try_revoke_row(model: type[models.Model], row_id: int) -> bool:
    """Try to revoke a grant from an independent connection without waiting."""

    connections.close_all()
    try:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            row = (
                model._base_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update(nowait=True)
                .get(pk=row_id)
            )
            row.delete(using=DEFAULT_DB_ALIAS)
        return True
    except DatabaseError:
        return False
    finally:
        connections.close_all()


def test_only_exact_price_limit_permission_yields_locked_principal(
    price_limit_permission: Permission,
) -> None:
    """A direct price-limit grant works and carries its own sealed purpose."""

    user = _new_user("price-limit-direct")
    user.user_permissions.add(price_limit_permission)
    repository = DjangoPriceLimitPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)

    with repository.locked_price_limit_publisher(_proof_for_user(user)) as principal:
        assert principal.actor_type == "django_user"
        assert principal.actor_id == f"django-user:{user.pk}"
        assert principal.permission_codename == _PRICE_LIMIT_PERMISSION
        assert principal.database_alias == DEFAULT_DB_ALIAS
        assert principal.user_id == user.pk
        assert principal.permission_id == price_limit_permission.pk
        assert principal.authority_content_hash.startswith("sha256:")
        assert principal.session_expires_at > principal.verified_at


@pytest.mark.parametrize(
    "codename",
    [_CALENDAR_PUBLISH_PERMISSION, _CALENDAR_AUDIT_PERMISSION],
)
def test_calendar_permission_never_substitutes_for_price_limit_permission(
    codename: str,
    price_limit_permission: Permission,
) -> None:
    """Calendar publish/read grants cannot authorize price-limit publication."""

    assert price_limit_permission.codename == _PRICE_LIMIT_PERMISSION
    calendar_permission = _permission("exchangecalendarsnapshotfactmodel", codename)
    user = _new_user(f"calendar-only-{codename}")
    user.user_permissions.add(calendar_permission)
    repository = DjangoPriceLimitPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)

    with pytest.raises(AuthorizationError) as caught:
        with repository.locked_price_limit_publisher(_proof_for_user(user)):
            pytest.fail("A Calendar permission must not authorize price-limit publication")

    assert caught.value.code == "PRICE_LIMIT_PUBLISHER_PERMISSION_REQUIRED"


@pytest.mark.parametrize(
    ("is_staff", "is_superuser"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_staff_and_superuser_are_not_permission_shortcuts(
    is_staff: bool,
    is_superuser: bool,
    price_limit_permission: Permission,
) -> None:
    """The kernel accepts persisted grants only, regardless of role flags."""

    assert price_limit_permission.codename == _PRICE_LIMIT_PERMISSION
    user = _new_user(
        f"price-limit-role-{is_staff}-{is_superuser}",
        is_staff=is_staff,
        is_superuser=is_superuser,
    )
    repository = DjangoPriceLimitPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)

    with pytest.raises(AuthorizationError) as caught:
        with repository.locked_price_limit_publisher(_proof_for_user(user)):
            pytest.fail("Staff or superuser flags must not grant the custom permission")

    assert caught.value.code == "PRICE_LIMIT_PUBLISHER_PERMISSION_REQUIRED"


def test_missing_permission_definition_fails_closed(
    price_limit_permission: Permission,
) -> None:
    """A missing custom permission definition never grants publisher access."""

    user = _new_user("price-limit-permission-missing")
    permission_id = price_limit_permission.pk
    content_type_id = price_limit_permission.content_type_id
    price_limit_permission.delete()
    assert not Permission.objects.filter(pk=permission_id).exists()
    assert ContentType.objects.filter(
        pk=content_type_id,
        app_label="data_center",
        model="pricelimitsnapshotfactmodel",
    ).exists()

    repository = DjangoPriceLimitPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)
    with pytest.raises(AuthorizationError) as caught:
        with repository.locked_price_limit_publisher(_proof_for_user(user)):
            pytest.fail("A missing permission definition must fail closed")

    assert caught.value.code == "PRICE_LIMIT_PUBLISHER_PERMISSION_UNAVAILABLE"


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row-lock race requires PostgreSQL")
@override_settings(SESSION_ENGINE="django.contrib.sessions.backends.db")
def test_postgres_price_limit_grant_revocation_waits_for_locked_principal(
    price_limit_permission: Permission,
) -> None:
    """A price-limit direct grant stays locked through the caller's transaction."""

    user = _new_user("price-limit-revocation")
    user.user_permissions.add(price_limit_permission)
    witness_model = User.user_permissions.through
    witness = witness_model.objects.get(user_id=user.pk, permission_id=price_limit_permission.pk)
    proof = _proof_for_user(user)
    repository = DjangoPriceLimitPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with repository.locked_price_limit_publisher(proof) as principal:
            assert (
                pool.submit(_try_revoke_row, witness_model, witness.pk).result(timeout=5) is False
            )
            principal.assert_live()
        assert pool.submit(_try_revoke_row, witness_model, witness.pk).result(timeout=5) is True

    with pytest.raises(AuthorizationError) as caught:
        with repository.locked_price_limit_publisher(proof):
            pytest.fail("A revoked price-limit grant must not be reused")

    assert caught.value.code == "PRICE_LIMIT_PUBLISHER_PERMISSION_REQUIRED"
