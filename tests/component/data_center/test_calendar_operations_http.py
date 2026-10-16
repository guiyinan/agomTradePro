"""Real session and CSRF HTTP journey for exchange-calendar operations.

The fixture deliberately skips SQLite: the locked publisher authority, formal
publication repository, and Audit outbox path are accepted only by the
Native PostgreSQL component run.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, cast

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.test import override_settings
from django.urls import include, path
from rest_framework.test import APIClient

from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
)
from apps.config_center.models import ConfigCenterSecretModel
from apps.data_center import calendar_snapshot_capture_composition as capture_composition
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetProviderBindingModel,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
    SchemaFingerprintModel,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from core.exceptions import DataFetchError
from tests.component.data_center.test_calendar_snapshot_capture_composition import (
    DATASET_KEY,
    _calendar_body,
    _central_secrets,
    _write_runtime_configuration,
)
from tests.component.data_center.test_formal_calendar_publication_postgres import (
    _SCHEMA_MODELS,
    _actual_publisher,
    _clear_auth_join_rows,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

_CAPTURE_PATH = "/api/data-center/exchange-calendars/snapshots/capture/"
_PREVIEW_PATH = "/api/data-center/exchange-calendars/publication-preview/"
_CONFIRM_PATH = "/api/data-center/exchange-calendars/publications/"
_CURRENT_PATH = "/api/data-center/exchange-calendars/current/"
_EXCHANGE = "SSE"
_ORIGIN = "https://testserver"

_HTTP_SCHEMA_MODELS = (
    *_SCHEMA_MODELS,
    ConfigCenterSecretModel,
    DatasetProviderBindingModel,
    ProviderConfigModel,
    SchemaFingerprintModel,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "apps.audit",
        "apps.config_center",
        "apps.data_center",
    ],
)


def _csrf_bootstrap(request: HttpRequest) -> JsonResponse:
    """Issue a real CSRF cookie and return its matching token for browser tests."""

    return JsonResponse({"csrf_token": get_token(request)})


urlpatterns = [
    path("csrf/bootstrap/", _csrf_bootstrap, name="test-csrf-bootstrap"),
    path(
        "api/data-center/",
        include(
            ("apps.data_center.interface.api_urls", "api_data_center"),
            namespace="api_data_center",
        ),
    ),
]


@pytest.fixture(autouse=True)
def _postgres_schema(
    django_db_blocker: object,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate only the auth, configuration, source, publication, and Audit tables."""

    if connection.vendor != "postgresql":
        pytest.skip("session-authority calendar HTTP journey requires Native PostgreSQL")
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(_HTTP_SCHEMA_MODELS):
            _clear_auth_join_rows()
            try:
                yield
            finally:
                _clear_auth_join_rows()


@pytest.fixture(autouse=True)
def _http_settings() -> Iterator[None]:
    """Use the real Data Center URLConf with only a test CSRF bootstrap route."""

    with override_settings(
        ROOT_URLCONF=__name__,
        AGOMTRADEPRO_ENCRYPTION_KEY="calendar-http-component-fixture-key",
    ):
        yield


def _client_for_user(username: str, *, csrf: bool = True) -> tuple[APIClient, Any, str | None]:
    """Authenticate through a persisted Django session and optionally acquire CSRF."""

    user, proof = _actual_publisher(username)
    client = APIClient(enforce_csrf_checks=True)
    client.cookies[settings.SESSION_COOKIE_NAME] = proof.session_key
    token: str | None = None
    if csrf:
        response = client.get("/csrf/bootstrap/", secure=True, HTTP_ORIGIN=_ORIGIN)
        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/json")
        payload = cast(dict[str, object], response.json())
        csrf_token = payload.get("csrf_token")
        assert type(csrf_token) is str
        token = csrf_token
    return client, user, token


def _post(
    client: APIClient,
    path_value: str,
    payload: dict[str, object],
    csrf_token: str | None,
) -> Any:
    """Send a secure JSON POST with the browser Origin and supplied CSRF token."""

    headers: dict[str, str] = {"HTTP_ORIGIN": _ORIGIN}
    if csrf_token is not None:
        headers["HTTP_X_CSRFTOKEN"] = csrf_token
    return client.post(path_value, payload, format="json", secure=True, **headers)


def _get(client: APIClient, path_value: str, **query: object) -> Any:
    """Send a secure JSON GET with a same-origin browser request header."""

    return client.get(path_value, query, secure=True, HTTP_ORIGIN=_ORIGIN)


def _json(response: Any, expected_status: int) -> dict[str, object]:
    """Assert a JSON response and narrow its body for contract assertions."""

    assert response.status_code == expected_status
    assert response["Content-Type"].startswith("application/json")
    body = response.json()
    assert isinstance(body, dict)
    return cast(dict[str, object], body)


def _object(value: object) -> dict[str, object]:
    """Narrow one presenter or intent mapping returned in the JSON envelope."""

    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _success_data(response: Any, expected_status: int) -> dict[str, object]:
    """Assert the shared success envelope and return its data projection."""

    body = _json(response, expected_status)
    assert body.get("outcome") == "success"
    assert body.get("success") is True
    return _object(body.get("data"))


def _install_source(
    monkeypatch: pytest.MonkeyPatch,
    response_bodies: Sequence[bytes],
) -> list[_Session]:
    """Patch only the central secret read and Tushare outbound HTTP boundary."""

    _write_runtime_configuration()
    monkeypatch.setattr(capture_composition, "get_secrets", lambda: _central_secrets())
    pending = iter(response_bodies)
    sessions: list[_Session] = []

    def new_session() -> _Session:
        response = _Response(next(pending))
        session = _Session(response)
        sessions.append(session)
        return session

    monkeypatch.setattr(tushare_client, "_create_requests_session", new_session)
    return sessions


def _changed_calendar_body() -> bytes:
    """Return a complete same-range source response with changed calendar content."""

    return _calendar_body().replace(
        b'["SSE","20261016",0,"20261015"]',
        b'["SSE","20261016",1,"20261015"]',
    )


def _formal_counts() -> tuple[int, int, int, int, int, int]:
    """Count durable publication, pointer, coverage/member, and Audit records."""

    return (
        CanonicalPublicationModel.objects.count(),
        CanonicalPublicationPointerModel.objects.count(),
        PublicationMemberModel.objects.count(),
        CoverageSnapshotModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )


def _source_counts() -> tuple[int, int]:
    """Count retained exact source responses and immutable calendar facts."""

    return RawPayloadModel.objects.count(), ExchangeCalendarSnapshotFactModel.objects.count()


def test_session_csrf_full_publish_forward_replay_and_revoked_current_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real browser sessions can capture, publish, retry, supersede, and read."""

    sessions = _install_source(monkeypatch, (_calendar_body(), _changed_calendar_body()))
    client, user, csrf_token = _client_for_user("calendar-http-publisher")
    assert csrf_token is not None

    captured = _success_data(
        _post(
            client,
            _CAPTURE_PATH,
            {
                "exchange": _EXCHANGE,
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            csrf_token,
        ),
        201,
    )
    first_preview = _success_data(
        _post(client, _PREVIEW_PATH, _object(captured["preview_intent"]), csrf_token),
        200,
    )
    first_confirmation = _object(first_preview["confirmation_intent"])
    first_commit = _success_data(
        _post(client, _CONFIRM_PATH, first_confirmation, csrf_token),
        201,
    )
    first_publication = _object(first_commit["publication"])
    after_first = _formal_counts()
    assert after_first[:6] == (1, 1, 1, 1, 1, 1)

    first_retry = _success_data(
        _post(client, _CONFIRM_PATH, first_confirmation, csrf_token),
        200,
    )
    assert _object(first_retry["publication"]) == first_publication
    assert _formal_counts() == after_first

    second_capture = _success_data(
        _post(
            client,
            _CAPTURE_PATH,
            {
                "exchange": _EXCHANGE,
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            csrf_token,
        ),
        201,
    )
    second_preview = _success_data(
        _post(client, _PREVIEW_PATH, _object(second_capture["preview_intent"]), csrf_token),
        200,
    )
    second_confirmation = _object(second_preview["confirmation_intent"])
    second_commit = _success_data(
        _post(client, _CONFIRM_PATH, second_confirmation, csrf_token),
        200,
    )
    second_publication = _object(second_commit["publication"])
    assert second_publication["publication_hash"] != first_publication["publication_hash"]
    after_forward = _formal_counts()
    assert after_forward[:6] == (2, 1, 2, 2, 2, 2)

    second_retry = _success_data(
        _post(client, _CONFIRM_PATH, second_confirmation, csrf_token),
        200,
    )
    assert _object(second_retry["publication"]) == second_publication
    assert _formal_counts() == after_forward

    _json(_post(client, _CONFIRM_PATH, first_confirmation, csrf_token), 409)

    permission = Permission.objects.get(
        content_type__app_label="data_center",
        codename="publish_exchange_calendar",
    )
    user.user_permissions.remove(permission)
    current = _success_data(
        _get(
            client,
            _CURRENT_PATH,
            dataset_key=DATASET_KEY,
            exchange=_EXCHANGE,
        ),
        200,
    )
    assert current["must_not_execute"] is True
    assert _object(current["publication"])["publication_id"] == second_publication["publication_id"]
    _json(_post(client, _CONFIRM_PATH, second_confirmation, csrf_token), 403)

    assert len(sessions) == 2
    assert all(session.response.closed for session in sessions)
    assert _source_counts() == (2, 2)
    assert _formal_counts() == after_forward


def test_anonymous_and_missing_csrf_requests_are_json_and_have_no_source_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authentication and CSRF reject before any provider call or persistence."""

    sessions = _install_source(monkeypatch, (_calendar_body(),))
    anonymous = APIClient(enforce_csrf_checks=True)
    anonymous_requests = (
        anonymous.post(
            _CAPTURE_PATH,
            {
                "exchange": _EXCHANGE,
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            format="json",
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
        ),
        anonymous.post(_PREVIEW_PATH, {}, format="json", secure=True, HTTP_ORIGIN=_ORIGIN),
        anonymous.post(_CONFIRM_PATH, {}, format="json", secure=True, HTTP_ORIGIN=_ORIGIN),
        anonymous.get(
            _CURRENT_PATH,
            {"dataset_key": DATASET_KEY, "exchange": _EXCHANGE},
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
        ),
    )
    for response in anonymous_requests:
        _json(response, 403)

    client, _user, _token = _client_for_user("calendar-http-no-csrf", csrf=False)
    _json(
        _post(
            client,
            _CAPTURE_PATH,
            {
                "exchange": _EXCHANGE,
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            None,
        ),
        403,
    )
    assert sessions == []
    assert _source_counts() == (0, 0)
    assert _formal_counts()[:6] == (0, 0, 0, 0, 0, 0)


def test_strict_http_rejects_actor_alias_and_client_clock_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller identity, database alias, and current-read time are server-owned."""

    _install_source(monkeypatch, (_calendar_body(),))
    client, _user, csrf_token = _client_for_user("calendar-http-strict-input")
    assert csrf_token is not None
    captured = _success_data(
        _post(
            client,
            _CAPTURE_PATH,
            {
                "exchange": _EXCHANGE,
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            csrf_token,
        ),
        201,
    )
    preview = _success_data(
        _post(client, _PREVIEW_PATH, _object(captured["preview_intent"]), csrf_token),
        200,
    )
    confirmation = _object(preview["confirmation_intent"])

    for forbidden_key in ("actor_id", "database_alias"):
        invalid = dict(confirmation)
        invalid[forbidden_key] = "client-controlled"
        _json(_post(client, _CONFIRM_PATH, invalid, csrf_token), 400)

    _json(
        _get(
            client,
            _CURRENT_PATH,
            dataset_key=DATASET_KEY,
            exchange=_EXCHANGE,
            as_of="2026-10-16T00:00:00Z",
        ),
        400,
    )
    assert _formal_counts()[:6] == (0, 0, 0, 0, 0, 0)
    assert _source_counts() == (1, 1)


def test_confirmation_rejects_catalog_ttl_drift_after_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale preview cannot publish after its same-version calendar TTL changes."""

    _install_source(monkeypatch, (_calendar_body(),))
    client, _user, csrf_token = _client_for_user("calendar-http-ttl-drift")
    assert csrf_token is not None
    captured = _success_data(
        _post(
            client,
            _CAPTURE_PATH,
            {
                "exchange": _EXCHANGE,
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            csrf_token,
        ),
        201,
    )
    preview = _success_data(
        _post(client, _PREVIEW_PATH, _object(captured["preview_intent"]), csrf_token),
        200,
    )
    DatasetContractModel.objects.filter(dataset_key=DATASET_KEY).update(
        calendar_response_max_age_seconds=901
    )

    error_body = _json(
        _post(
            client,
            _CONFIRM_PATH,
            _object(preview["confirmation_intent"]),
            csrf_token,
        ),
        409,
    )
    assert error_body.get("code") == "CALENDAR_PUBLICATION_PREVIEW_STALE"
    assert _formal_counts()[:6] == (0, 0, 0, 0, 0, 0)
    assert _source_counts() == (1, 1)


def test_outbox_failure_rolls_back_formal_publication_but_keeps_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTTP boundary reports 503 after the outer transaction removes partial writes."""

    _install_source(monkeypatch, (_calendar_body(),))
    client, _user, csrf_token = _client_for_user("calendar-http-outbox-failure")
    assert csrf_token is not None
    captured = _success_data(
        _post(
            client,
            _CAPTURE_PATH,
            {
                "exchange": _EXCHANGE,
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            csrf_token,
        ),
        201,
    )
    preview = _success_data(
        _post(client, _PREVIEW_PATH, _object(captured["preview_intent"]), csrf_token),
        200,
    )

    def fail_after_event(*_args: object, **_kwargs: object) -> None:
        assert CanonicalPublicationModel.objects.count() == 1
        assert CanonicalPublicationPointerModel.objects.count() == 1
        assert SystemAuditEventModel.objects.count() == 1
        raise DataFetchError(
            "injected calendar outbox enqueue failure",
            code="TEST_CALENDAR_OUTBOX_FAILURE",
        )

    monkeypatch.setattr(DjangoSystemAuditOutboxRepository, "enqueue_targeted", fail_after_event)
    error_body = _json(
        _post(
            client,
            _CONFIRM_PATH,
            _object(preview["confirmation_intent"]),
            csrf_token,
        ),
        503,
    )
    assert error_body.get("code") == "CALENDAR_PUBLICATION_AUDIT_UNAVAILABLE"
    assert _formal_counts()[:6] == (0, 0, 0, 0, 0, 0)
    assert _source_counts() == (1, 1)


def test_http_method_media_and_accept_contracts_are_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The four operation routes retain explicit HTTP method and JSON contracts."""

    _install_source(monkeypatch, (_calendar_body(),))
    client, _user, csrf_token = _client_for_user("calendar-http-media-contract")
    assert csrf_token is not None

    _json(
        client.get(_CAPTURE_PATH, secure=True, HTTP_ORIGIN=_ORIGIN),
        405,
    )
    _json(
        client.post(
            _CAPTURE_PATH,
            data=b"{}",
            content_type="text/plain",
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
            HTTP_X_CSRFTOKEN=csrf_token,
        ),
        415,
    )
    _json(
        client.get(
            _CURRENT_PATH,
            {"dataset_key": DATASET_KEY, "exchange": _EXCHANGE},
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
            HTTP_ACCEPT="text/html",
        ),
        406,
    )
    assert _source_counts() == (0, 0)
    assert _formal_counts()[:6] == (0, 0, 0, 0, 0, 0)
