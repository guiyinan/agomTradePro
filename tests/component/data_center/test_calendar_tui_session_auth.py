"""Real outer TUI Session/CSRF gate and inner calendar authority probe.

The owner probe acquires the actual calendar authority fence, but does not
capture, preview or publish business data. This is not the Calendar TUI journey.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Iterator
from typing import Any

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.test import override_settings
from django.urls import include, path, resolve
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from apps.account.infrastructure.identity_models import AccountProfileModel, UserAccessTokenModel
from apps.account.interface.authentication import TerminalInternalAuthentication
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.calendar_publication_authority_composition import (
    locked_calendar_publisher_for_request,
)
from apps.data_center.infrastructure.fact_and_operational_models import RawPayloadModel
from apps.data_center.infrastructure.publication_rollback_models import CanonicalPublicationModel
from apps.terminal.infrastructure.tui_adapters import TuiInternalActionExecutor
from apps.terminal.interface import api_views as tui_views
from tests.component.data_center.test_formal_calendar_publication_postgres import (
    _SCHEMA_MODELS,
    _actual_publisher,
    _clear_auth_join_rows,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.test_tui_workbench import FakeMetadataRepository, _metadata_payload

_ORIGIN = "https://testserver"
_SESSION_ACTION = "test.calendar-session-probe"
_LEGACY_ACTION = "test.compatibility-probe"
_AUTH_SECRET = "calendar-tui-component-internal-auth-fixture"
_OWNER_PATH = "/api/test-owner/calendar-authority/"
_LEGACY_PATH = "/api/test-owner/compatibility/"


class _AuthorityProbe(APIView):
    """Exercise the real same-process owner request claim and locked authority."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    seen: list[dict[str, object]] = []

    def post(self, request: Request) -> Response:
        """Record identity only after the real authority context commits."""

        with locked_calendar_publisher_for_request(request, using="default") as principal:
            observed: dict[str, object] = {
                "user_id": request.user.pk,
                "session_key": request.session.session_key,
                "alias": request.user._state.db,
                "principal_user_id": principal.user_id,
                "authenticator_is_session": type(request.successful_authenticator)
                is SessionAuthentication,
                "inner_csrf_disabled": request._request._dont_enforce_csrf_checks,
            }
        self.seen.append(observed)
        return Response({"outcome": "success", "data": {"status": "authority_checked"}})


class _CompatibilityProbe(APIView):
    """Keep a non-calendar legacy owner independent of the new metadata flag."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    calls = 0

    def post(self, request: Request) -> Response:
        """Return a passive fixture result without a calendar authority claim."""

        type(self).calls += 1
        return Response({"outcome": "success", "data": {"status": "legacy_read"}})


def _csrf_bootstrap(request: HttpRequest) -> JsonResponse:
    """Issue CSRF through the real response middleware."""

    return JsonResponse({"csrf_token": get_token(request)})


urlpatterns = [
    path("test-csrf/", _csrf_bootstrap),
    path("api/test-owner/calendar-authority/", _AuthorityProbe.as_view()),
    path("api/test-owner/compatibility/", _CompatibilityProbe.as_view()),
    path("", include("core.urls")),
]


class _CountingExecutor(TuiInternalActionExecutor):
    """Observe dispatch while retaining the real internal request factory."""

    calls: int = 0

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Count every owner dispatch and delegate unchanged."""

        self.calls += 1
        return super().execute(**kwargs)


@pytest.fixture(autouse=True)
def _postgres_schema(
    django_db_setup: None, django_db_blocker: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Keep the full app registry and clear only the explicit fixture tables.

    Direct django_db_setup plus our unblock context avoids a TransactionTestCase
    flush of every Account governance table. Restricting available_apps would
    hide the real user__account_profile token relation.
    """

    del django_db_setup
    if connection.vendor != "postgresql":
        pytest.skip("TUI calendar authority bridge requires Native PostgreSQL")
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    with django_db_blocker.unblock():
        with isolated_schema((*_SCHEMA_MODELS, AccountProfileModel, UserAccessTokenModel)):
            _clear_auth_join_rows()
            try:
                yield
            finally:
                _clear_auth_join_rows()


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, str, _CountingExecutor]]:
    """Substitute metadata only; authenticate and dispatch with production classes."""

    actions = [
        {
            "key": key,
            "label": "会话核验" if flagged else "兼容读取",
            "method": "POST",
            "endpoint": endpoint,
            "intent": "read",
            "screen_key": "command-center.overview",
            "module_key": "command-center",
            "view_type": "status",
            "risk": "read",
            "effect": "read",
            "fields": [],
            "source": "approved:test",
            "raw_debug": False,
            "session_auth_required": flagged,
        }
        for key, endpoint, flagged in (
            (_SESSION_ACTION, _OWNER_PATH, True),
            (_LEGACY_ACTION, _LEGACY_PATH, False),
        )
    ]
    repository = FakeMetadataRepository(_metadata_payload(actions=actions))
    executor = _CountingExecutor()
    monkeypatch.setattr(tui_views, "get_tui_metadata_repository", lambda: repository)
    monkeypatch.setattr(tui_views, "get_tui_action_executor", lambda: executor)
    _AuthorityProbe.seen = []
    _CompatibilityProbe.calls = 0
    with override_settings(
        ROOT_URLCONF=__name__,
        AGOMTRADEPRO_INTERNAL_AUTH_SECRET=_AUTH_SECRET,
        AGOMTRADEPRO_ENCRYPTION_KEY="calendar-tui-component-encryption-fixture",
    ):
        user, proof = _actual_publisher("calendar-tui-session-user")
        AccountProfileModel.objects.create(
            user=user, display_name="Calendar fixture", mcp_enabled=True
        )
        yield user, proof.session_key, executor


def _path(action_key: str = _SESSION_ACTION) -> str:
    """Use the actual action-run production route."""

    value = f"/api/tui/actions/{action_key}/run/"
    assert resolve(value).func.view_class is tui_views.TuiWorkbenchActionRunView
    return value


def _session_client(session_key: str) -> tuple[APIClient, str]:
    """Persist cookie identity and acquire a real matching CSRF cookie/token."""

    client = APIClient(enforce_csrf_checks=True)
    client.cookies[settings.SESSION_COOKIE_NAME] = session_key
    response = client.get("/test-csrf/", secure=True, HTTP_ORIGIN=_ORIGIN)
    assert response.status_code == 200
    token = response.json()["csrf_token"]
    assert type(token) is str
    return client, token


def _post(
    client: APIClient,
    *,
    action_key: str = _SESSION_ACTION,
    csrf_token: str | None = None,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """Send a real HTTPS JSON request through Django middleware."""

    options = {"HTTP_ORIGIN": _ORIGIN, **(headers or {})}
    if csrf_token is not None:
        options["HTTP_X_CSRFTOKEN"] = csrf_token
    response = client.post(
        _path(action_key), body or {"params": {}}, format="json", secure=True, **options
    )
    assert response["Content-Type"].startswith("application/json")
    return response


def _formal_counts() -> tuple[int, int, int, int]:
    """Reject accidental capture or formal event writes by the passive probe."""

    return (
        RawPayloadModel.objects.count(),
        CanonicalPublicationModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )


def test_real_session_csrf_passes_actual_inner_calendar_authority(
    runtime: tuple[Any, str, _CountingExecutor],
) -> None:
    user, session_key, executor = runtime
    client, csrf = _session_client(session_key)
    response = _post(client, csrf_token=csrf)
    assert response.status_code == 200, response.json()
    assert response.json()["outcome"] == "success"
    assert executor.calls == 1
    assert _AuthorityProbe.seen == [
        {
            "user_id": user.pk,
            "session_key": session_key,
            "alias": "default",
            "principal_user_id": user.pk,
            "authenticator_is_session": True,
            "inner_csrf_disabled": True,
        }
    ]
    assert _formal_counts() == (0, 0, 0, 0)


def test_missing_outer_csrf_blocks_before_any_internal_dispatch(
    runtime: tuple[Any, str, _CountingExecutor],
) -> None:
    _user, session_key, executor = runtime
    client, _csrf = _session_client(session_key)
    response = _post(client)
    assert response.status_code == 403
    assert executor.calls == 0 and _AuthorityProbe.seen == []
    assert _formal_counts() == (0, 0, 0, 0)


def test_anonymous_outer_request_with_csrf_never_dispatches(
    runtime: tuple[Any, str, _CountingExecutor],
) -> None:
    _user, _session_key, executor = runtime
    client = APIClient(enforce_csrf_checks=True)
    bootstrap = client.get("/test-csrf/", secure=True, HTTP_ORIGIN=_ORIGIN)
    response = _post(client, csrf_token=bootstrap.json()["csrf_token"])
    assert response.status_code == 403
    assert executor.calls == 0 and _AuthorityProbe.seen == []
    assert _formal_counts() == (0, 0, 0, 0)


@pytest.mark.parametrize("credential", ["token", "internal"])
def test_real_non_session_auth_is_rejected_and_legacy_action_still_runs(
    runtime: tuple[Any, str, _CountingExecutor], credential: str
) -> None:
    user, _session_key, executor = runtime
    if credential == "token":
        token, raw_key = UserAccessTokenModel.create_token(user=user, name="tui-gate-fixture")
        headers = {"HTTP_AUTHORIZATION": "Token " + raw_key}
    else:
        timestamp = str(int(time.time()))
        payload = TerminalInternalAuthentication._build_signature_payload(
            timestamp=timestamp,
            method="POST",
            path=_path(),
            user_id=str(user.pk),
            username=user.username,
        )
        signature = hmac.new(_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {
            "HTTP_X_AGOM_INTERNAL_SIGNATURE": signature,
            "HTTP_X_AGOM_INTERNAL_TIMESTAMP": timestamp,
            "HTTP_X_AGOM_INTERNAL_USER_ID": str(user.pk),
            "HTTP_X_AGOM_INTERNAL_USERNAME": user.username,
        }
    client = APIClient(enforce_csrf_checks=True)
    response = _post(client, headers=headers, body={"params": {}, "session_auth_required": False})
    assert response.status_code == 403, response.json()
    assert response.json()["error_code"] == "tui_session_auth_required"
    assert executor.calls == 0 and _AuthorityProbe.seen == []
    if credential == "token":
        token.refresh_from_db()
        assert token.last_used_at is not None
    else:
        payload = TerminalInternalAuthentication._build_signature_payload(
            timestamp=timestamp,
            method="POST",
            path=_path(_LEGACY_ACTION),
            user_id=str(user.pk),
            username=user.username,
        )
        headers["HTTP_X_AGOM_INTERNAL_SIGNATURE"] = hmac.new(
            _AUTH_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
    compatibility = _post(client, action_key=_LEGACY_ACTION, headers=headers)
    assert compatibility.status_code == 200, compatibility.json()
    assert compatibility.json()["outcome"] == "success"
    assert executor.calls == 1 and _CompatibilityProbe.calls == 1
    assert _AuthorityProbe.seen == []
    assert _formal_counts() == (0, 0, 0, 0)


def test_outer_session_gate_does_not_replace_owner_permission_check(
    runtime: tuple[Any, str, _CountingExecutor],
) -> None:
    user, session_key, executor = runtime
    permission = Permission.objects.get(codename="publish_exchange_calendar")
    user.user_permissions.remove(permission)
    client, csrf = _session_client(session_key)
    response = _post(client, csrf_token=csrf)
    assert response.status_code == 200, response.json()
    assert response.json()["response"]["status_code"] == 403
    assert response.json()["outcome"] == "failed"
    assert executor.calls == 1 and _AuthorityProbe.seen == []
    assert _formal_counts() == (0, 0, 0, 0)
