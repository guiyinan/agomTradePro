"""Session-authenticated, explicitly permissioned calendar publisher context."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connection, connections, models, transaction
from django.http import HttpRequest, HttpResponse
from django.test import override_settings
from django.urls import path
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from apps.data_center.application.calendar_publication_authority import (
    CalendarPublisherSessionRequestProof,
)
from apps.data_center.calendar_publication_authority_composition import (
    locked_calendar_publisher_for_request,
)
from apps.data_center.infrastructure.calendar_publication_authority_repository import (
    DjangoCalendarPublisherAuthorityRepository,
)
from core.exceptions import AuthorizationError
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
    ],
)

User = get_user_model()
_PERMISSION_CODENAME = "publish_exchange_calendar"


class _CalendarAuthorityProbeView(APIView):
    """Expose only the authority proof needed to exercise the request adapter."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        """Set a real CSRF cookie before the unsafe session-authenticated request."""

        from django.middleware.csrf import get_token

        get_token(request._request)
        return Response({"ready": True})

    def post(self, request: Request) -> Response:
        """Return locked actor metadata without writing a publication or audit event."""

        with locked_calendar_publisher_for_request(request, using="default") as principal:
            return Response(
                {
                    "actor_type": principal.actor_type,
                    "actor_id": principal.actor_id,
                    "permission_codename": principal.permission_codename,
                    "database_alias": principal.database_alias,
                    "user_id": principal.user_id,
                    "verified_at": principal.verified_at.isoformat(),
                }
            )


class _CsrfCookieView:
    """Provide the middleware response hook required for a test-only CSRF route."""

    @staticmethod
    @ensure_csrf_cookie
    def get(_request: HttpRequest) -> HttpResponse:
        """Issue a CSRF cookie for the API client."""

        return HttpResponse("ok")


urlpatterns = [
    path("_test/calendar-authority/", _CalendarAuthorityProbeView.as_view()),
    path("_test/csrf/", _CsrfCookieView.get),
]


@pytest.fixture(autouse=True)
def _auth_schema(
    django_db_blocker: object,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Build only authentication tables and suppress unrelated account provisioning."""

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


@pytest.fixture
def publisher_permission() -> Permission:
    """Create the exact test permission; this fixture grants no production user."""

    content_type, _ = ContentType.objects.get_or_create(
        app_label="data_center",
        model="exchangecalendarsnapshotfactmodel",
    )
    if (
        content_type.app_label != "data_center"
        or content_type.model != "exchangecalendarsnapshotfactmodel"
    ):
        raise AssertionError("Existing content type does not match the calendar fact model")
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename=_PERMISSION_CODENAME,
        defaults={"name": "Can publish exchange calendar snapshots"},
    )
    if permission.content_type_id != content_type.pk or permission.codename != _PERMISSION_CODENAME:
        raise AssertionError("Existing permission does not match the calendar publisher contract")
    return permission


def _new_user(username: str, *, is_staff: bool = False, is_superuser: bool = False) -> Any:
    """Create a local user for an actual Django session login journey."""

    return User.objects.create_user(
        username=username,
        password="test-only-calendar-password",
        is_active=True,
        is_staff=is_staff,
        is_superuser=is_superuser,
    )


def _authenticated_client(user: Any) -> APIClient:
    """Log in through Django and acquire a CSRF cookie through middleware."""

    client = APIClient(enforce_csrf_checks=True)
    assert client.login(username=user.username, password="test-only-calendar-password")
    response = client.get("/_test/csrf/")
    assert response.status_code == 200
    return client


def _post(client: APIClient, *, csrf: bool = True) -> Any:
    """Send a real POST through SessionAuthentication and optional CSRF validation."""

    headers: dict[str, str] = {}
    if csrf:
        headers["HTTP_X_CSRFTOKEN"] = client.cookies["csrftoken"].value
    return client.post("/_test/calendar-authority/", {}, format="json", **headers)


def _proof_for_user(user: Any) -> CalendarPublisherSessionRequestProof:
    """Persist the exact Django session witnesses for PostgreSQL lock candidates."""

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
    return CalendarPublisherSessionRequestProof(
        user_id=int(user.pk),
        session_key=session_key,
        request_authenticated_at=now,
        request_user_database_alias=DEFAULT_DB_ALIAS,
        database_alias=DEFAULT_DB_ALIAS,
    )


def _try_revoke_row(model: type[models.Model], row_id: int) -> bool:
    """Try to lock and remove one grant witness on an independent DB connection."""

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


@override_settings(ROOT_URLCONF=__name__)
def test_only_explicit_direct_permission_yields_locked_session_principal(
    publisher_permission: Permission,
) -> None:
    """A real login plus direct custom permission yields exact actor attribution."""

    user = _new_user("calendar-direct")
    user.user_permissions.add(publisher_permission)
    client = _authenticated_client(user)

    response = _post(client)

    assert response.status_code == 200
    assert response.data["actor_type"] == "django_user"
    assert response.data["actor_id"] == f"django-user:{user.pk}"
    assert response.data["permission_codename"] == _PERMISSION_CODENAME
    assert response.data["database_alias"] == "default"
    assert response.data["user_id"] == user.pk
    assert response.data["verified_at"]
    assert "session" not in response.data


@override_settings(ROOT_URLCONF=__name__)
@pytest.mark.parametrize(
    ("is_staff", "is_superuser"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_staff_and_superuser_shortcuts_do_not_grant_calendar_publication(
    is_staff: bool,
    is_superuser: bool,
    publisher_permission: Permission,
) -> None:
    """Only a persisted explicit grant can authorize, independent of role flags."""

    assert publisher_permission.codename == _PERMISSION_CODENAME
    user = _new_user(
        f"calendar-denied-{is_staff}-{is_superuser}",
        is_staff=is_staff,
        is_superuser=is_superuser,
    )

    response = _post(_authenticated_client(user))

    assert response.status_code == 403


@override_settings(ROOT_URLCONF=__name__)
def test_group_permission_is_rechecked_from_persisted_rows(
    publisher_permission: Permission,
) -> None:
    """A permission inherited through a concrete group witness is accepted."""

    user = _new_user("calendar-group")
    group = Group.objects.create(name="calendar publishers")
    group.permissions.add(publisher_permission)
    user.groups.add(group)

    response = _post(_authenticated_client(user))

    assert response.status_code == 200
    assert response.data["actor_id"] == f"django-user:{user.pk}"


@override_settings(ROOT_URLCONF=__name__)
def test_session_authenticated_post_still_requires_real_csrf_token(
    publisher_permission: Permission,
) -> None:
    """The real DRF SessionAuthentication path rejects a missing CSRF header."""

    user = _new_user("calendar-csrf")
    user.user_permissions.add(publisher_permission)

    response = _post(_authenticated_client(user), csrf=False)

    assert response.status_code == 403


@override_settings(ROOT_URLCONF=__name__)
def test_forced_identity_is_not_accepted_as_session_proof(
    publisher_permission: Permission,
) -> None:
    """A test-style forced user or caller-supplied identity is not a session login."""

    user = _new_user("calendar-forced")
    user.user_permissions.add(publisher_permission)
    client = APIClient(enforce_csrf_checks=True)
    client.force_authenticate(user=user)

    response = client.post("/_test/calendar-authority/", {"user_id": user.pk}, format="json")

    assert response.status_code == 401


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row-lock race requires PostgreSQL")
@pytest.mark.parametrize(
    "grant_kind",
    ["direct", "group_membership", "group_permission"],
)
@override_settings(SESSION_ENGINE="django.contrib.sessions.backends.db")
def test_postgres_grant_revocation_cannot_cross_locked_principal(
    grant_kind: str,
    publisher_permission: Permission,
) -> None:
    """PostgreSQL row locks serialize direct, membership, and group grant revocation."""

    user = _new_user(f"calendar-race-{grant_kind}")
    group = Group.objects.create(name=f"calendar-race-{grant_kind}")
    if grant_kind == "direct":
        user.user_permissions.add(publisher_permission)
        witness_model = User.user_permissions.through
        witness = witness_model.objects.get(
            user_id=user.pk,
            permission_id=publisher_permission.pk,
        )
    elif grant_kind == "group_membership":
        group.permissions.add(publisher_permission)
        user.groups.add(group)
        witness_model = User.groups.through
        witness = witness_model.objects.get(user_id=user.pk, group_id=group.pk)
    elif grant_kind == "group_permission":
        group.permissions.add(publisher_permission)
        user.groups.add(group)
        witness_model = Group.permissions.through
        witness = witness_model.objects.get(
            group_id=group.pk,
            permission_id=publisher_permission.pk,
        )
    else:
        raise AssertionError(f"Unknown grant witness: {grant_kind}")

    proof = _proof_for_user(user)
    repository = DjangoCalendarPublisherAuthorityRepository(using=DEFAULT_DB_ALIAS)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with repository.locked_calendar_publisher(proof) as principal:
            assert (
                pool.submit(_try_revoke_row, witness_model, witness.pk).result(timeout=5) is False
            )
            principal.assert_live()
        assert pool.submit(_try_revoke_row, witness_model, witness.pk).result(timeout=5) is True

    with pytest.raises(AuthorizationError):
        with repository.locked_calendar_publisher(proof):
            pass
