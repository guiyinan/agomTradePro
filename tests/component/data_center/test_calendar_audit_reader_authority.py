"""Real SessionAuthentication checks for the dedicated calendar audit reader."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import DEFAULT_DB_ALIAS
from django.http import HttpRequest, HttpResponse
from django.test import override_settings
from django.urls import path
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from apps.data_center.calendar_publication_authority_composition import (
    locked_calendar_publisher_for_request,
)
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
_CONTENT_TYPE_MODEL = "exchangecalendarsnapshotfactmodel"
_PUBLISH_PERMISSION = "publish_exchange_calendar"
_READ_PERMISSION = "view_exchange_calendar_publication_audit"


class _CalendarAuditReaderProbeView(APIView):
    """Exercise the public read-authority composition from a real DRF request."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        """Return only the exact read principal fields needed by this test."""

        from core.integration.calendar_publication_audit_reader import (
            build_calendar_publication_audit_read_authority_provider,
        )

        provider = build_calendar_publication_audit_read_authority_provider()
        lease = provider.lock_reader(
            request_proof=request,
            dataset_key="exchange.calendar.days",
            exchange="SSE",
            database_alias=DEFAULT_DB_ALIAS,
        )
        if lease is None:
            return Response({"error": "reader provider unavailable"}, status=503)
        with lease as context:
            context.assert_live()
            return Response(
                {
                    "actor_id": context.actor_id,
                    "authority_content_hash": context.authority_content_hash,
                    "database_alias": context.database_alias,
                    "dataset_key": context.dataset_key,
                    "exchange": context.exchange,
                    "permission_codename": context.permission_codename,
                    "session_expires_at": context.session_expires_at.isoformat(),
                    "user_id": context.user_id,
                    "verified_at": context.verified_at.isoformat(),
                }
            )


class _CalendarPublisherProbeView(APIView):
    """Exercise the existing POST-only publisher proof for separation checks."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        """Return the publisher permission observed under lock."""

        with locked_calendar_publisher_for_request(request, using=DEFAULT_DB_ALIAS) as principal:
            return Response({"permission_codename": principal.permission_codename})


class _CsrfCookieView:
    """Issue a real CSRF cookie for the publisher POST separation check."""

    @staticmethod
    @ensure_csrf_cookie
    def get(_request: HttpRequest) -> HttpResponse:
        """Set the cookie consumed by a session-authenticated POST."""

        return HttpResponse("ok")


urlpatterns = [
    path("_test/calendar-audit-reader/", _CalendarAuditReaderProbeView.as_view()),
    path("_test/calendar-publisher/", _CalendarPublisherProbeView.as_view()),
    path("_test/calendar-reader-csrf/", _CsrfCookieView.get),
]


def _test_server_error(_request: HttpRequest) -> HttpResponse:
    """Keep test-only unhandled errors concise when the scoped app set is small."""

    return HttpResponse("test server error", status=500)


handler500 = _test_server_error


@pytest.fixture(autouse=True)
def _auth_schema(
    django_db_blocker: object,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Create only auth/session tables and avoid unrelated account signal writes."""

    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    model_types = (ContentType, Permission, Group, User)
    from django.contrib.sessions.models import Session

    model_types = (*model_types, Session)
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(model_types):
            try:
                yield
            finally:
                User.user_permissions.through.objects.all().delete()
                User.groups.through.objects.all().delete()
                Group.permissions.through.objects.all().delete()


def _permission(codename: str) -> Permission:
    """Create or verify one exact permission definition without granting it."""

    content_type, _ = ContentType.objects.get_or_create(
        app_label="data_center",
        model=_CONTENT_TYPE_MODEL,
    )
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename=codename,
        defaults={"name": f"Calendar test {codename}"},
    )
    if (
        permission.content_type_id != content_type.pk
        or permission.codename != codename
        or content_type.app_label != "data_center"
        or content_type.model != _CONTENT_TYPE_MODEL
    ):
        raise AssertionError("Calendar permission definition has an unexpected identity")
    return permission


def _new_user(
    username: str,
    *,
    is_staff: bool = False,
    is_superuser: bool = False,
) -> Any:
    """Create an active test user for a genuine cookie-backed session."""

    return User.objects.create_user(
        username=username,
        password="test-only-calendar-password",
        is_active=True,
        is_staff=is_staff,
        is_superuser=is_superuser,
    )


def _client_for(user: Any) -> APIClient:
    """Log in through Django; GET needs no CSRF token under SessionAuthentication."""

    client = APIClient(enforce_csrf_checks=True)
    client.raise_request_exception = False
    assert client.login(username=user.username, password="test-only-calendar-password")
    return client


@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_real_session_get_yields_only_explicit_calendar_audit_read_principal() -> None:
    """A real GET session plus the dedicated read permission yields a live principal."""

    user = _new_user("calendar-audit-reader-direct")
    user.user_permissions.add(_permission(_READ_PERMISSION))
    client = _client_for(user)

    response = client.get("/_test/calendar-audit-reader/")

    assert response.status_code == 200
    assert response.data["actor_id"] == f"django-user:{user.pk}"
    assert response.data["permission_codename"] == _READ_PERMISSION
    assert response.data["database_alias"] == "default"
    assert response.data["dataset_key"] == "exchange.calendar.days"
    assert response.data["exchange"] == "SSE"
    assert response.data["user_id"] == user.pk
    assert response.data["verified_at"]
    assert response.data["session_expires_at"]
    assert response.data["authority_content_hash"].startswith("sha256:")
    assert len(response.data["authority_content_hash"]) == len("sha256:") + 64


@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_publisher_permission_does_not_grant_calendar_audit_read() -> None:
    """The reader wrapper checks its own permission rather than the write grant."""

    user = _new_user("calendar-audit-reader-publisher-only")
    user.user_permissions.add(_permission(_PUBLISH_PERMISSION))

    response = _client_for(user).get("/_test/calendar-audit-reader/")

    assert response.status_code == 403


@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_calendar_audit_read_permission_does_not_grant_publisher_post() -> None:
    """The existing POST publisher continues to require its separate permission."""

    user = _new_user("calendar-audit-reader-cannot-publish")
    user.user_permissions.add(_permission(_READ_PERMISSION))
    client = _client_for(user)
    assert client.get("/_test/calendar-reader-csrf/").status_code == 200

    response = client.post(
        "/_test/calendar-publisher/",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("is_staff", "is_superuser"),
    [(False, False), (True, False), (False, True), (True, True)],
)
@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_role_flags_do_not_grant_calendar_audit_read(
    is_staff: bool,
    is_superuser: bool,
) -> None:
    """Staff and superuser flags cannot replace the explicit read permission."""

    user = _new_user(
        f"calendar-audit-role-{is_staff}-{is_superuser}",
        is_staff=is_staff,
        is_superuser=is_superuser,
    )

    response = _client_for(user).get("/_test/calendar-audit-reader/")

    assert response.status_code == 403


@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_calendar_audit_read_permission_can_be_granted_by_exact_group_row() -> None:
    """A concrete group grant is accepted for the current authenticated session."""

    user = _new_user("calendar-audit-reader-group")
    group = Group.objects.create(name="calendar audit readers")
    group.permissions.add(_permission(_READ_PERMISSION))
    user.groups.add(group)

    response = _client_for(user).get("/_test/calendar-audit-reader/")

    assert response.status_code == 200
    assert response.data["permission_codename"] == _READ_PERMISSION
