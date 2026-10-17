"""Native session/CSRF journey for the calendar publication workbench."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from time import sleep
from typing import Any, cast
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import connection
from django.http import HttpResponse
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from pytest_django.plugin import DjangoDbBlocker
from rest_framework.test import APIClient

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.config_center.models import ConfigCenterSecretModel
from apps.data_center import calendar_snapshot_capture_composition as capture_composition
from apps.data_center import calendar_workbench_current_composition as current_composition
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
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
from apps.data_center.interface import calendar_workbench_api_views as workbench_views
from shared.config.secrets import clear_secrets_cache
from tests.component.data_center.test_calendar_snapshot_capture_composition import (
    DATASET_KEY,
    _calendar_body,
    _central_secrets,
    _write_runtime_configuration,
)
from tests.component.data_center.test_formal_calendar_publication_postgres import (
    _SCHEMA_MODELS as _PUBLICATION_SCHEMA_MODELS,
)
from tests.component.data_center.test_formal_calendar_publication_postgres import (
    _actual_publisher,
    _clear_auth_join_rows,
)
from tests.support.isolated_schema import isolated_schema
from tests.support.native_postgres_database import (
    assert_native_postgres_test_database,
)
from tests.support.native_postgres_database import (  # noqa: F401
    native_postgres_test_database as _native_postgres_test_database_fixture,
)
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

_ORIGIN = "https://testserver"
_EXCHANGE = "SSE"
_ENCRYPTION_KEY = urlsafe_b64encode(bytes(range(32))).decode("ascii")

_HTTP_SCHEMA_MODELS = (
    *_PUBLICATION_SCHEMA_MODELS,
    AccountProfileModel,
    ConfigCenterSecretModel,
    DatasetProviderBindingModel,
    ProviderConfigModel,
    SchemaFingerprintModel,
)

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="calendar workbench session and Audit journey requires Native PostgreSQL",
)


@pytest.fixture(autouse=True)
def _native_calendar_schema(
    django_db_setup: str,
    django_db_blocker: DjangoDbBlocker,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate the exact authentication, source, catalog, publication and Audit rows."""

    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")

    def verify_database_before_cleanup() -> None:
        """Stop before any cleanup if this connection no longer targets TEST.NAME."""

        assert_native_postgres_test_database(expected_name=django_db_setup)

    with django_db_blocker.unblock():
        verify_database_before_cleanup()
        with isolated_schema(
            _HTTP_SCHEMA_MODELS,
            before_cleanup=verify_database_before_cleanup,
        ):
            _clear_auth_join_rows()
            try:
                yield
            finally:
                verify_database_before_cleanup()
                _clear_auth_join_rows()


@pytest.fixture(scope="session")
def django_db_setup(native_postgres_test_database: str) -> str:
    """Bind this module to the shared explicit TEST.NAME setup."""

    return native_postgres_test_database


@pytest.fixture(autouse=True)
def _http_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Use the project URLConf and keep the synthetic encryption key out of settings."""

    with override_settings(AGOMTRADEPRO_ENCRYPTION_KEY=None):
        monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", _ENCRYPTION_KEY)
        clear_secrets_cache()
        try:
            yield
        finally:
            clear_secrets_cache()


def _publisher_client(
    username: str,
    *,
    csrf: bool = True,
) -> tuple[APIClient, Any, object, str | None]:
    """Create a real persisted publisher session and optionally acquire real CSRF."""

    user, proof = _actual_publisher(username)
    client, token = _session_client(proof.session_key, csrf=csrf)
    return client, user, proof, token


def _session_client(session_key: str, *, csrf: bool = True) -> tuple[APIClient, str | None]:
    """Bind a persisted Django session and obtain CSRF from the real admin login page."""

    client = APIClient(enforce_csrf_checks=True)
    client.cookies[settings.SESSION_COOKIE_NAME] = session_key
    token: str | None = None
    if csrf:
        response = client.get(reverse("admin:login"), secure=True, HTTP_ORIGIN=_ORIGIN)
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/html")
        csrf_cookie = client.cookies.get(settings.CSRF_COOKIE_NAME)
        assert csrf_cookie is not None
        token = csrf_cookie.value
    return client, token


def _second_session_for_user(user: object) -> str:
    """Persist a second valid session for the same user, without fabricating proof."""

    user_id = getattr(user, "pk", None)
    session_hash = getattr(user, "get_session_auth_hash", None)
    assert type(user_id) is int and callable(session_hash)
    session_key = uuid4().hex
    authenticated_at = timezone.now().astimezone(UTC)
    Session.objects.create(
        session_key=session_key,
        session_data=SessionStore().encode(
            {
                "_auth_user_id": str(user_id),
                "_auth_user_backend": settings.AUTHENTICATION_BACKENDS[0],
                "_auth_user_hash": session_hash(),
            }
        ),
        expire_date=authenticated_at + timedelta(minutes=10),
    )
    return session_key


def _post(
    client: APIClient,
    path_value: str,
    payload: dict[str, object],
    csrf_token: str | None,
) -> HttpResponse:
    """Send a secure JSON POST with same-origin browser and optional CSRF headers."""

    headers: dict[str, str] = {"HTTP_ORIGIN": _ORIGIN}
    if csrf_token is not None:
        headers["HTTP_X_CSRFTOKEN"] = csrf_token
    return cast(
        HttpResponse,
        client.post(path_value, payload, format="json", secure=True, **headers),
    )


def _get_current(client: APIClient) -> HttpResponse:
    """Read the workbench current endpoint using only its user-selected exchange."""

    return cast(
        HttpResponse,
        client.get(
            _workbench_url("current"),
            {"exchange": _EXCHANGE},
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
        ),
    )


def _get_formal_current(client: APIClient) -> HttpResponse:
    """Keep the original exact-current endpoint journey alongside Workbench read."""

    return cast(
        HttpResponse,
        client.get(
            reverse("api_data_center:dc-calendar-current"),
            {"dataset_key": DATASET_KEY, "exchange": _EXCHANGE},
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
        ),
    )


def _workbench_url(action: str) -> str:
    """Resolve the production Data Center route rather than a test URLConf copy."""

    return reverse(f"api_data_center:dc-calendar-workbench-{action}")


def _activate_new_calendar_contract_with_ttl(ttl_seconds: int) -> DatasetContractModel:
    """Version the selected catalog while retaining the published version as immutable."""

    old_contract = DatasetContractModel.objects.get(dataset_key=DATASET_KEY, active=True)
    old_policy = DatasetPublicationPolicyModel.objects.get(dataset_key=DATASET_KEY, active=True)
    old_binding = DatasetProviderBindingModel.objects.get(
        dataset_key=DATASET_KEY,
        contract_version=old_contract.contract_version,
        schema_version=old_contract.schema_version,
        enabled=True,
    )
    DatasetPublicationPolicyModel.objects.filter(pk=old_policy.pk).update(active=False)
    DatasetContractModel.objects.filter(pk=old_contract.pk).update(active=False)
    DatasetProviderBindingModel.objects.filter(pk=old_binding.pk).update(enabled=False)

    contract_version = "3.0"
    new_contract = DatasetContractModel.objects.create(
        dataset_key=old_contract.dataset_key,
        contract_version=contract_version,
        schema_version=old_contract.schema_version,
        owner=old_contract.owner,
        frequency=old_contract.frequency,
        decision_critical=old_contract.decision_critical,
        fields=old_contract.fields,
        freshness_seconds=old_contract.freshness_seconds,
        execution_freshness_seconds=old_contract.execution_freshness_seconds,
        calendar_response_max_age_seconds=ttl_seconds,
        comparable_group=old_contract.comparable_group,
        active=True,
    )
    DatasetPublicationPolicyModel.objects.create(
        dataset_key=old_policy.dataset_key,
        contract_version=contract_version,
        schema_version=old_policy.schema_version,
        policy_version="calendar-v3",
        member_codec_version=old_policy.member_codec_version,
        minimum_coverage_ratio=old_policy.minimum_coverage_ratio,
        allow_partial=old_policy.allow_partial,
        conflict_action=old_policy.conflict_action,
        required_evidence=old_policy.required_evidence,
        retention_days=old_policy.retention_days,
        active=True,
    )
    DatasetProviderBindingModel.objects.create(
        dataset_key=old_binding.dataset_key,
        contract_version=contract_version,
        schema_version=old_binding.schema_version,
        provider=old_binding.provider,
        capability=old_binding.capability,
        priority=old_binding.priority,
        freshness_seconds=old_binding.freshness_seconds,
        validator_key=old_binding.validator_key,
        enabled=True,
    )
    return new_contract


def _json(response: HttpResponse, expected_status: int) -> dict[str, object]:
    """Assert a JSON response and narrow its envelope."""

    assert response.status_code == expected_status
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _object(value: object) -> dict[str, object]:
    """Narrow a JSON object at the test boundary."""

    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _success_data(response: HttpResponse, expected_status: int) -> dict[str, object]:
    """Assert the common success envelope and return its data projection."""

    payload = _json(response, expected_status)
    assert payload.get("outcome") == "success"
    assert payload.get("success") is True
    return _object(payload.get("data"))


def _prepare(
    client: APIClient,
    csrf_token: str,
) -> tuple[dict[str, object], str]:
    """Capture and preview one full explicit SSE range, returning visible data and token."""

    payload = _json(
        _post(
            client,
            _workbench_url("prepare"),
            {
                "exchange": _EXCHANGE,
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            csrf_token,
        ),
        201,
    )
    assert payload.get("outcome") == "success"
    assert payload.get("success") is True
    visible = _object(payload.get("data"))
    continuation = _object(payload.get("continuation"))
    token_input = _object(continuation.get("input"))
    token = token_input.get("confirmation_token")
    assert type(token) is str
    assert token.startswith("encrypted:v1:")
    assert continuation.get("action_key") == "data-center.calendar-workbench-confirm"
    return visible, token


def _confirm(client: APIClient, csrf_token: str, token: str) -> HttpResponse:
    """Submit only the opaque continuation accepted by the strict confirmation API."""

    return _post(
        client,
        _workbench_url("confirm"),
        {"confirmation_token": token},
        csrf_token,
    )


def _install_source(
    monkeypatch: pytest.MonkeyPatch,
    response_bodies: Sequence[bytes],
    *,
    response_factory: Callable[[bytes], _Response] = _Response,
) -> list[_Session]:
    """Use real source/catalog/RawPayload code with only secrets and HTTP stubbed."""

    _write_runtime_configuration()
    monkeypatch.setattr(capture_composition, "get_secrets", lambda: _central_secrets())
    pending = iter(response_bodies)
    sessions: list[_Session] = []

    def new_session() -> _Session:
        response = response_factory(next(pending))
        session = _Session(response)
        sessions.append(session)
        return session

    monkeypatch.setattr(tushare_client, "_create_requests_session", new_session)
    return sessions


def _changed_calendar_body() -> bytes:
    """Return a second complete response with one date's open flag changed."""

    changed = _calendar_body().replace(
        b'["SSE","20261016",0,"20261015"]',
        b'["SSE","20261016",1,"20261015"]',
    )
    assert changed != _calendar_body()
    return changed


def _source_counts() -> tuple[int, int]:
    """Count immutable retained responses and calendar facts."""

    return RawPayloadModel.objects.count(), ExchangeCalendarSnapshotFactModel.objects.count()


def _formal_counts() -> tuple[int, int, int, int, int, int]:
    """Count formal publication, current pointer, members, coverage, events and outbox."""

    return (
        CanonicalPublicationModel.objects.count(),
        CanonicalPublicationPointerModel.objects.count(),
        PublicationMemberModel.objects.count(),
        CoverageSnapshotModel.objects.count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )


def test_real_session_prepare_confirm_retry_forward_current_and_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive source capture, publication, retries, revocation and configured current reads."""

    responses = _install_source(
        monkeypatch,
        (_calendar_body(), _changed_calendar_body(), _changed_calendar_body()),
    )
    client, user, _proof, csrf_token = _publisher_client("calendar-workbench-native-publisher")
    assert csrf_token is not None

    first_visible, first_token = _prepare(client, csrf_token)
    assert first_visible["publication_status"] == "preview"
    assert first_visible["must_not_execute"] is True
    assert _source_counts() == (1, 1)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)

    first_response = _success_data(_confirm(client, csrf_token, first_token), 201)
    assert first_response["transition_label"] == "日历已首次发布"
    first_counts = _formal_counts()
    assert first_counts == (1, 1, 1, 1, 1, 1)

    first_retry = _success_data(_confirm(client, csrf_token, first_token), 200)
    assert first_retry["transition_label"] == "当前日历版本已再次确认"
    assert _formal_counts() == first_counts

    _old_preview, old_token = _prepare(client, csrf_token)
    _new_preview, new_token = _prepare(client, csrf_token)
    forward = _success_data(_confirm(client, csrf_token, new_token), 200)
    assert forward["transition_label"] == "日历版本已更新"
    forwarded_counts = _formal_counts()
    assert forwarded_counts == (2, 1, 2, 2, 2, 2)

    stale = _json(_confirm(client, csrf_token, old_token), 409)
    assert stale.get("code") in {
        "CALENDAR_PUBLICATION_POINTER_CHANGED",
        "CALENDAR_PUBLICATION_PREVIEW_STALE",
    }
    assert _formal_counts() == forwarded_counts

    forward_retry = _success_data(_confirm(client, csrf_token, new_token), 200)
    assert forward_retry["transition_label"] == "当前日历版本已再次确认"
    assert _formal_counts() == forwarded_counts

    permission = Permission.objects.get(
        content_type__app_label="data_center",
        codename="publish_exchange_calendar",
    )
    user.user_permissions.remove(permission)

    current_data = _success_data(_get_current(client), 200)
    assert current_data["configuration_status"] == "metadata_selected"
    assert current_data["current_status"] == "published"
    current = _object(current_data["current"])
    assert current["must_not_execute"] is True
    assert current["must_not_use_for_decision"] is True
    assert current["publication_status"] == "published"
    original_expiry = current["response_expires_at"]
    assert type(original_expiry) is str

    # Preserve the original exact-current endpoint contract as a separate route.
    formal_current = _success_data(_get_formal_current(client), 200)
    assert formal_current["must_not_execute"] is True

    new_contract = _activate_new_calendar_contract_with_ttl(ttl_seconds=1)
    scope_data = _success_data(
        cast(
            HttpResponse,
            client.get(_workbench_url("scope"), secure=True, HTTP_ORIGIN=_ORIGIN),
        ),
        200,
    )
    assert scope_data["metadata_status"] == "metadata_selected", scope_data["blocked_reason"]
    assert scope_data["blocked_reason"] is None
    assert _object(scope_data["metadata"])["calendar_response_max_age_seconds"] == 1
    after_ttl_update = _success_data(_get_current(client), 200)
    assert after_ttl_update["current_status"] == "published"
    assert _object(after_ttl_update["current"])["response_expires_at"] == original_expiry

    DatasetContractModel.objects.filter(pk=new_contract.pk).update(active=False)
    current_owner_calls: list[object] = []
    monkeypatch.setattr(
        current_composition,
        "read_current_exchange_calendar",
        lambda intent: current_owner_calls.append(intent),
    )
    blocked_data = _success_data(_get_current(client), 200)
    assert blocked_data["configuration_status"] == "blocked"
    assert blocked_data["current_status"] == "blocked"
    assert blocked_data["blocked_reason"]
    assert blocked_data["current"] is None
    assert current_owner_calls == []

    assert _json(_confirm(client, csrf_token, new_token), 403).get("code")

    assert responses[1].response.body == responses[2].response.body
    # Each response occurrence has its own completion time in the immutable raw envelope.
    assert _source_counts() == (3, 3)
    assert _formal_counts() == forwarded_counts
    assert len(responses) == 3
    assert all(session.response.closed for session in responses)


def test_workbench_routes_are_mounted_by_the_project_urlconf() -> None:
    """The native component exercises production route names, not local copies."""

    assert _workbench_url("scope") == "/api/data-center/exchange-calendars/workbench/scope/"
    assert _workbench_url("current") == "/api/data-center/exchange-calendars/workbench/current/"
    assert _workbench_url("prepare") == "/api/data-center/exchange-calendars/workbench/prepare/"
    assert _workbench_url("confirm") == "/api/data-center/exchange-calendars/workbench/confirm/"


@pytest.mark.parametrize(
    "query_string",
    (
        "exchange=SSE&exchange=SSE",
        "exchange=SSE&exchange=SZSE",
        "exchange=SSE&actor_id=django-user%3A11",
        "exchange=SSE&user_id=11",
        "exchange=SSE&database_alias=default",
        "exchange=SSE&dataset_key=tushare.exchange_calendar.raw",
        "exchange=SSE&as_of=2026-10-17T00%3A00%3A00Z",
    ),
)
def test_authenticated_current_rejects_duplicate_and_unknown_query_before_owner(
    monkeypatch: pytest.MonkeyPatch,
    query_string: str,
) -> None:
    """A real session without publish permission cannot smuggle current-read scope."""

    user, proof = _actual_publisher(f"calendar-workbench-query-{uuid4().hex}")
    permission = Permission.objects.get(
        content_type__app_label="data_center",
        codename="publish_exchange_calendar",
    )
    user.user_permissions.remove(permission)
    client, _csrf_token = _session_client(proof.session_key, csrf=False)
    owner_calls: list[str] = []

    def unexpected_owner_call(exchange: str) -> object:
        owner_calls.append(exchange)
        raise AssertionError("Invalid query reached the current owner composition")

    monkeypatch.setattr(workbench_views, "read_calendar_workbench_current", unexpected_owner_call)
    response = cast(
        HttpResponse,
        client.get(
            f"{_workbench_url('current')}?{query_string}",
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
        ),
    )

    payload = _json(response, 400)
    assert payload.get("code") or payload.get("exchange")
    assert owner_calls == []


def test_token_tamper_actor_and_same_actor_new_session_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opaque continuations remain bound to their exact actor and session."""

    _install_source(monkeypatch, (_calendar_body(),))
    owner_client, owner, _proof, owner_csrf = _publisher_client("calendar-workbench-token-owner")
    assert owner_csrf is not None
    _visible, token = _prepare(owner_client, owner_csrf)

    middle = len("encrypted:v1:") + 20
    replacement = "A" if token[middle] != "A" else "B"
    tampered_token = token[:middle] + replacement + token[middle + 1 :]
    tampered = _json(_confirm(owner_client, owner_csrf, tampered_token), 400)
    assert str(tampered.get("code", "")).startswith("CALENDAR_PREVIEW_TOKEN_")

    other_client, _other_user, _other_proof, other_csrf = _publisher_client(
        "calendar-workbench-token-other-actor"
    )
    assert other_csrf is not None
    other_actor = _json(_confirm(other_client, other_csrf, token), 409)
    assert str(other_actor.get("code", "")).startswith("CALENDAR_PREVIEW_TOKEN_")

    second_session_key = _second_session_for_user(owner)
    second_session_client, second_session_csrf = _session_client(second_session_key)
    assert second_session_csrf is not None
    changed_session = _json(
        _confirm(second_session_client, second_session_csrf, token),
        409,
    )
    assert str(changed_session.get("code", "")).startswith("CALENDAR_PREVIEW_TOKEN_")

    assert _source_counts() == (1, 1)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)


def test_expired_original_response_window_blocks_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmation expires from captured response time and does not refresh it."""

    _install_source(monkeypatch, (_calendar_body(),))
    DatasetContractModel.objects.filter(dataset_key=DATASET_KEY).update(
        calendar_response_max_age_seconds=5
    )
    client, _user, _proof, csrf_token = _publisher_client("calendar-workbench-expired-token")
    assert csrf_token is not None
    visible, token = _prepare(client, csrf_token)
    expiry_text = visible.get("response_expires_at")
    assert type(expiry_text) is str
    expiry = datetime.fromisoformat(expiry_text.replace("Z", "+00:00"))
    delay = max(0.0, (expiry - timezone.now()).total_seconds()) + 0.05
    assert delay <= 5.2
    sleep(delay)
    expired = _json(_confirm(client, csrf_token, token), 409)
    assert expired.get("code") == "CALENDAR_PREVIEW_TOKEN_EXPIRED"
    assert _source_counts() == (1, 1)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)


def test_missing_csrf_and_missing_encryption_key_have_bounded_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CSRF blocks before capture; key loss after capture preserves only source facts."""

    class _RemoveEncryptionKeyResponse(_Response):
        """Remove only the synthetic key after the real transport releases its body."""

        def close(self) -> None:
            """Release the body first, then make token encryption unavailable."""

            super().close()
            monkeypatch.delenv("AGOMTRADEPRO_ENCRYPTION_KEY", raising=False)
            clear_secrets_cache()

    responses = _install_source(
        monkeypatch,
        (_calendar_body(),),
        response_factory=_RemoveEncryptionKeyResponse,
    )
    no_csrf_client, _user, _proof, _token = _publisher_client(
        "calendar-workbench-no-csrf",
        csrf=False,
    )
    denied = _json(
        _post(
            no_csrf_client,
            _workbench_url("prepare"),
            {
                "exchange": _EXCHANGE,
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            None,
        ),
        403,
    )
    assert denied.get("code")
    assert responses == []
    assert _source_counts() == (0, 0)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)

    client, _key_user, _key_proof, csrf_token = _publisher_client(
        "calendar-workbench-encryption-key-unavailable"
    )
    assert csrf_token is not None
    unavailable = _json(
        _post(
            client,
            _workbench_url("prepare"),
            {
                "exchange": _EXCHANGE,
                "coverage_start": "2026-10-15",
                "coverage_end": "2026-10-16",
            },
            csrf_token,
        ),
        503,
    )
    assert unavailable.get("code") == "CALENDAR_PREVIEW_TOKEN_KEY_UNAVAILABLE"
    assert responses and all(session.response.closed for session in responses)
    assert _source_counts() == (1, 1)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)
