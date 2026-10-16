"""Authorization must remain valid until its owned transaction commits."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import transaction
from django.test import override_settings

from apps.data_center.application.calendar_publication_authority import (
    CalendarPublisherSessionRequestProof,
)
from apps.data_center.infrastructure.calendar_publication_authority_repository import (
    DjangoCalendarPublisherAuthorityRepository,
)
from core.exceptions import AuthenticationError, AuthorizationError
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
    ],
)
UserModel = cast(type[User], get_user_model())
NOW = datetime.now(UTC)


class _Clock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant


@pytest.fixture(autouse=True)
def _auth_schema(django_db_blocker: object, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((ContentType, Permission, Group, UserModel, Session)):
            try:
                yield
            finally:
                UserModel.user_permissions.through.objects.all().delete()
                UserModel.groups.through.objects.all().delete()
                Group.permissions.through.objects.all().delete()


def _proof() -> tuple[User, CalendarPublisherSessionRequestProof]:
    user = UserModel.objects.create_user(username="clock-boundary", is_active=True)
    content_type, _ = ContentType.objects.get_or_create(
        app_label="data_center", model="exchangecalendarsnapshotfactmodel"
    )
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename="publish_exchange_calendar",
        defaults={"name": "Test-only calendar permission"},
    )
    user.user_permissions.add(permission)
    session_key = "a" * 32
    Session.objects.create(
        session_key=session_key,
        session_data=SessionStore().encode(
            {
                SESSION_KEY: str(user.pk),
                BACKEND_SESSION_KEY: settings.AUTHENTICATION_BACKENDS[0],
                HASH_SESSION_KEY: user.get_session_auth_hash(),
            }
        ),
        expire_date=NOW + timedelta(seconds=60),
    )
    return user, CalendarPublisherSessionRequestProof(
        user_id=cast(int, user.pk),
        session_key=session_key,
        request_authenticated_at=NOW,
        request_user_database_alias="default",
        database_alias="default",
    )


@override_settings(SESSION_ENGINE="django.contrib.sessions.backends.db")
@pytest.mark.parametrize("call_assert_live", [True, False])
def test_session_expiry_inside_context_rolls_back_owned_write(call_assert_live: bool) -> None:
    user, proof = _proof()
    clock = _Clock(NOW + timedelta(seconds=10))
    repository = DjangoCalendarPublisherAuthorityRepository(using="default", clock=clock)
    with pytest.raises(AuthenticationError):
        with repository.locked_calendar_publisher(proof) as principal:
            UserModel.objects.filter(pk=user.pk).update(last_name="must-rollback")
            clock.instant = NOW + timedelta(seconds=60)
            if call_assert_live:
                principal.assert_live()
    user.refresh_from_db()
    assert user.last_name == ""


@override_settings(SESSION_ENGINE="django.contrib.sessions.backends.db")
def test_lock_window_clock_rollback_after_request_still_blocks_commit() -> None:
    user, proof = _proof()
    clock = _Clock(NOW + timedelta(seconds=10))
    repository = DjangoCalendarPublisherAuthorityRepository(using="default", clock=clock)
    with pytest.raises(AuthenticationError):
        with repository.locked_calendar_publisher(proof):
            UserModel.objects.filter(pk=user.pk).update(last_name="must-rollback")
            # Still after authentication; only a comparison with the last checked instant catches it.
            clock.instant = NOW + timedelta(seconds=5)
    user.refresh_from_db()
    assert user.last_name == ""


@override_settings(SESSION_ENGINE="django.contrib.sessions.backends.db")
def test_principal_cannot_cross_to_a_different_thread_transaction() -> None:
    _, proof = _proof()
    repository = DjangoCalendarPublisherAuthorityRepository(
        using="default",
        clock=_Clock(NOW + timedelta(seconds=10)),
    )
    with repository.locked_calendar_publisher(proof) as principal:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(principal.assert_live)
            with pytest.raises(AuthorizationError):
                future.result(timeout=5)
        principal.assert_live()


@override_settings(SESSION_ENGINE="django.contrib.sessions.backends.db")
@pytest.mark.parametrize("call_assert_live", [True, False])
def test_rollback_only_authority_transaction_cannot_report_success(
    call_assert_live: bool,
) -> None:
    user, proof = _proof()
    repository = DjangoCalendarPublisherAuthorityRepository(
        using="default",
        clock=_Clock(NOW + timedelta(seconds=10)),
    )
    with pytest.raises(AuthorizationError):
        with repository.locked_calendar_publisher(proof) as principal:
            UserModel.objects.filter(pk=user.pk).update(last_name="cannot-commit")
            transaction.set_rollback(True, using="default")
            if call_assert_live:
                principal.assert_live()
    user.refresh_from_db()
    assert user.last_name == ""
