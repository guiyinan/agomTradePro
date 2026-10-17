"""Native end-to-end Calendar Workbench journey through the real TUI API."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator, Sequence
from typing import Any, cast

import pytest
from django.db import connection
from django.http import HttpResponse
from django.test import override_settings
from django.urls import resolve, reverse
from pytest_django.plugin import DjangoDbBlocker
from rest_framework.test import APIClient

from apps.account.infrastructure.identity_models import AccountProfileModel, UserAccessTokenModel
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.terminal.infrastructure.models import TerminalAuditLogORM
from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository
from apps.terminal.interface import api_views as tui_views
from shared.config.secrets import clear_secrets_cache
from tests.component.data_center.test_calendar_workbench_http import (
    _ENCRYPTION_KEY,
    _HTTP_SCHEMA_MODELS,
    _calendar_body,
    _changed_calendar_body,
    _formal_counts,
    _install_source,
    _json,
    _publisher_client,
    _source_counts,
)
from tests.component.data_center.test_formal_calendar_publication_postgres import (
    _clear_auth_join_rows,
)
from tests.support.isolated_schema import isolated_schema
from tests.support.native_postgres_database import (
    assert_native_postgres_test_database,
)
from tests.support.native_postgres_database import (  # noqa: F401
    native_postgres_test_database as _native_postgres_test_database_fixture,
)

_ORIGIN = "https://testserver"
_SCREEN_KEY = "data-center.calendar-workbench"
_ACTION_PREFIX = "data-center.calendar-workbench-"
_ACTION_KEYS = frozenset(
    f"{_ACTION_PREFIX}{suffix}" for suffix in ("scope", "current", "prepare", "confirm")
)

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Calendar TUI outer-to-owner journey requires Native PostgreSQL",
)


class _FileRuntimeMetadataRepository:
    """Keep actual published-file/IA/runtime metadata while bypassing ORM version choice."""

    def __init__(self) -> None:
        self._payload = PublishedTuiMetadataRepository()._load_published_file()

    def load_published(self, registry_key: str = "default") -> dict[str, Any]:
        """Return a copy of the production-normalized file payload for one registry."""

        if registry_key != "default":
            raise AssertionError("Calendar TUI component uses only the default metadata registry")
        return copy.deepcopy(self._payload)


@pytest.fixture(autouse=True)
def _native_calendar_tui_schema(
    django_db_setup: str,
    django_db_blocker: DjangoDbBlocker,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Use the explicit TEST.NAME database and isolate only journey-owned tables."""

    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")

    def verify_database_before_cleanup() -> None:
        """Abort cleanup if the native connection no longer targets TEST.NAME."""

        assert_native_postgres_test_database(expected_name=django_db_setup)

    models = (*_HTTP_SCHEMA_MODELS, UserAccessTokenModel, TerminalAuditLogORM)
    with django_db_blocker.unblock():
        verify_database_before_cleanup()
        with isolated_schema(models, before_cleanup=verify_database_before_cleanup):
            _clear_auth_join_rows()
            try:
                yield
            finally:
                verify_database_before_cleanup()
                _clear_auth_join_rows()


@pytest.fixture(scope="session")
def django_db_setup(native_postgres_test_database: str) -> str:
    """Use the shared explicit native test database configured by TEST.NAME."""

    return native_postgres_test_database


@pytest.fixture(autouse=True)
def _synthetic_preview_encryption_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Supply only a local synthetic preview-key value and clear its cache."""

    with override_settings(AGOMTRADEPRO_ENCRYPTION_KEY=None):
        monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", _ENCRYPTION_KEY)
        clear_secrets_cache()
        try:
            yield
        finally:
            clear_secrets_cache()


def _install_actual_calendar_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> _FileRuntimeMetadataRepository:
    """Use production file normalization, IA and runtime injection for this test."""

    repository = _FileRuntimeMetadataRepository()
    payload = repository.load_published()
    actions = {
        str(action.get("key") or ""): action
        for action in payload.get("actions", [])
        if isinstance(action, dict) and action.get("screen_key") == _SCREEN_KEY
    }
    assert set(actions) == _ACTION_KEYS
    assert all(
        action.get("source") == "approved:runtime-calendar-workbench" for action in actions.values()
    )
    assert all(action.get("session_auth_required") is True for action in actions.values())
    assert all(action.get("raw_debug") is False for action in actions.values())
    assert actions[f"{_ACTION_PREFIX}prepare"]["result_continuation"] == {
        "target_action_key": f"{_ACTION_PREFIX}confirm",
        "field_map": {"confirmation_token": "confirmation_token"},
    }
    monkeypatch.setattr(tui_views, "get_tui_metadata_repository", lambda: repository)
    return repository


def _make_staff_publisher(username: str) -> tuple[APIClient, Any, str]:
    """Create a real granted publisher session and the staff audience needed by TUI."""

    client, user, _proof, csrf_token = _publisher_client(username)
    assert csrf_token is not None
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return client, user, csrf_token


def _run_tui_action(
    client: APIClient,
    *,
    action_key: str,
    params: dict[str, object],
    csrf_token: str | None,
    confirmed: bool | None = None,
) -> tuple[HttpResponse, dict[str, Any]]:
    """Post one action through the project root URLConf and real CSRF middleware."""

    path = reverse("api-tui-action-run", kwargs={"action_key": action_key})
    match = resolve(path)
    assert match.func.view_class is tui_views.TuiWorkbenchActionRunView
    body: dict[str, object] = {"params": params}
    if confirmed is not None:
        body["confirmed"] = confirmed
    headers: dict[str, str] = {"HTTP_ORIGIN": _ORIGIN}
    if csrf_token is not None:
        headers["HTTP_X_CSRFTOKEN"] = csrf_token
    response = cast(
        HttpResponse,
        client.post(path, body, format="json", secure=True, **headers),
    )
    assert response["Content-Type"].startswith("application/json")
    return response, cast(dict[str, Any], response.json())


def _screen_actions(client: APIClient) -> dict[str, dict[str, Any]]:
    """Read the screen compiled from actual runtime metadata through the root route."""

    path = reverse("api-tui-screen", kwargs={"screen_key": _SCREEN_KEY})
    match = resolve(path)
    assert match.func.view_class is tui_views.TuiWorkbenchScreenView
    response = cast(HttpResponse, client.get(path, secure=True, HTTP_ORIGIN=_ORIGIN))
    payload = _json(response, 200)
    actions = payload.get("actions")
    assert isinstance(actions, list)
    selected = {
        str(action.get("key") or ""): cast(dict[str, Any], action)
        for action in actions
        if isinstance(action, dict)
    }
    return selected


def _continuation_token(payload: dict[str, Any]) -> str:
    """Return the owner-issued runtime-only continuation from one TUI response."""

    continuation = payload.get("continuation")
    assert isinstance(continuation, dict)
    assert set(continuation) == {"action_key", "input", "expires_at"}
    assert continuation.get("action_key") == f"{_ACTION_PREFIX}confirm"
    token_input = continuation.get("input")
    assert isinstance(token_input, dict) and set(token_input) == {"confirmation_token"}
    token = token_input.get("confirmation_token")
    assert type(token) is str and token.startswith("encrypted:v1:")
    assert type(continuation.get("expires_at")) is str
    return token


def _assert_continuation_is_not_rendered(
    payload: dict[str, Any],
    token: str,
) -> None:
    """Keep the handoff out of every user-facing and debug projection."""

    display_projection = {
        key: payload.get(key)
        for key in (
            "action",
            "view_model",
            "debug",
            "business_summary",
            "blocking_reason",
            "next_steps",
            "debug_hidden_fields",
        )
    }
    assert token not in json.dumps(display_projection, ensure_ascii=False, default=str)
    debug = payload.get("debug")
    assert debug == {"raw_available": False, "raw_response": None}


def _assert_continuation_is_not_audited(tokens: Sequence[str]) -> None:
    """Check real TUI and formal Audit persistence for leaked owner tokens."""

    tui_rows = list(TerminalAuditLogORM.objects.values_list("params_summary", flat=True))
    assert tui_rows
    tui_payloads = [json.loads(value) for value in tui_rows]
    for audit_payload in tui_payloads:
        assert "continuation" not in audit_payload
        assert "continuation" not in audit_payload.get("result", {})
    persisted = "\n".join(
        (
            *[str(value) for value in tui_rows],
            json.dumps(list(SystemAuditEventModel.objects.values()), default=str),
            json.dumps(list(SystemAuditOutboxModel.objects.values()), default=str),
        )
    )
    for token in tokens:
        assert token not in persisted


def test_calendar_tui_outer_journey_uses_real_runtime_metadata_and_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run reads, confirmation barriers, publication, CAS replay, and revocation via TUI."""

    responses = _install_source(
        monkeypatch,
        (_calendar_body(), _changed_calendar_body(), _changed_calendar_body(), _calendar_body()),
    )
    _install_actual_calendar_runtime(monkeypatch)
    client, user, csrf_token = _make_staff_publisher("calendar-workbench-tui-owner")

    action_map = _screen_actions(client)
    assert set(action_map) == _ACTION_KEYS
    prepare_action = action_map[f"{_ACTION_PREFIX}prepare"]
    confirm_action = action_map[f"{_ACTION_PREFIX}confirm"]
    assert prepare_action.get("result_continuation") == {
        "target_action_key": f"{_ACTION_PREFIX}confirm",
        "field_map": {"confirmation_token": "confirmation_token"},
    }
    assert any(
        field.get("key") == "confirmation_token" and field.get("input_type") == "hidden"
        for field in confirm_action.get("fields", [])
    )

    scope_response, scope = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}scope",
        params={},
        csrf_token=csrf_token,
    )
    assert scope_response.status_code == 200
    assert scope.get("outcome") == "success"
    assert _source_counts() == (0, 0)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)

    current_response, current = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}current",
        params={"exchange": "SSE"},
        csrf_token=csrf_token,
    )
    assert current_response.status_code == 200
    assert current.get("outcome") == "success"
    assert current.get("response", {}).get("status_code") == 200
    assert current["view_model"]["status"] == "无当前版本"
    assert "没有已发布" in current["view_model"]["message"]
    assert _source_counts() == (0, 0)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)

    params = {
        "exchange": "SSE",
        "coverage_start": "2026-10-15",
        "coverage_end": "2026-10-16",
    }
    prepare_blocked_response, prepare_blocked = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}prepare",
        params=params,
        csrf_token=csrf_token,
        confirmed=False,
    )
    assert prepare_blocked_response.status_code == 200
    assert prepare_blocked.get("confirmation_required") is True
    assert prepare_blocked.get("response", {}).get("status_code") == 409
    assert _source_counts() == (0, 0)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)
    assert not responses

    prepare_response, first_preview = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}prepare",
        params=params,
        csrf_token=csrf_token,
        confirmed=True,
    )
    assert prepare_response.status_code == 200
    assert first_preview.get("outcome") == "success"
    assert first_preview.get("response", {}).get("status_code") == 201
    assert len(responses) == 1
    assert _source_counts() == (1, 1)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)
    first_token = _continuation_token(first_preview)
    issued_tokens = [first_token]
    _assert_continuation_is_not_rendered(first_preview, first_token)

    confirm_blocked_response, confirm_blocked = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}confirm",
        params={"confirmation_token": first_token},
        csrf_token=csrf_token,
        confirmed=False,
    )
    assert confirm_blocked_response.status_code == 200
    assert confirm_blocked.get("confirmation_required") is True
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)
    assert len(responses) == 1

    first_publish_response, first_publish = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}confirm",
        params={"confirmation_token": first_token},
        csrf_token=csrf_token,
        confirmed=True,
    )
    assert first_publish_response.status_code == 200
    assert first_publish.get("outcome") == "success"
    assert first_publish.get("response", {}).get("status_code") == 201
    assert "日历已首次发布" in json.dumps(first_publish.get("view_model"), ensure_ascii=False)
    first_counts = _formal_counts()
    assert first_counts == (1, 1, 1, 1, 1, 1)

    published_read_response, published_read = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}current",
        params={"exchange": "SSE"},
        csrf_token=csrf_token,
    )
    assert published_read_response.status_code == 200
    calendar_view = published_read["view_model"]
    assert calendar_view["kind"] == "datagrid"
    assert [column["label"] for column in calendar_view["columns"]] == [
        "日期",
        "状态",
        "前一开市日",
    ]
    assert [row["calendar_date"] for row in calendar_view["rows"]] == ["2026-10-15", "2026-10-16"]
    assert [row["calendar_state"] for row in calendar_view["rows"]] == ["开市", "休市"]
    assert "上游观测时间未知" in calendar_view["business_summary"]
    assert "不可用于交易或投资决策" in calendar_view["business_summary"]
    assert _formal_counts() == first_counts
    assert _source_counts() == (1, 1)

    first_replay_response, first_replay = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}confirm",
        params={"confirmation_token": first_token},
        csrf_token=csrf_token,
        confirmed=True,
    )
    assert first_replay_response.status_code == 200
    assert first_replay.get("response", {}).get("status_code") == 200
    assert _formal_counts() == first_counts

    _old_prepare_response, old_preview = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}prepare",
        params=params,
        csrf_token=csrf_token,
        confirmed=True,
    )
    old_token = _continuation_token(old_preview)
    issued_tokens.append(old_token)
    _assert_continuation_is_not_rendered(old_preview, old_token)
    assert _formal_counts() == first_counts

    _new_prepare_response, new_preview = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}prepare",
        params=params,
        csrf_token=csrf_token,
        confirmed=True,
    )
    new_token = _continuation_token(new_preview)
    issued_tokens.append(new_token)
    _assert_continuation_is_not_rendered(new_preview, new_token)
    assert _formal_counts() == first_counts

    forward_response, forward = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}confirm",
        params={"confirmation_token": new_token},
        csrf_token=csrf_token,
        confirmed=True,
    )
    assert forward_response.status_code == 200
    assert forward.get("response", {}).get("status_code") == 200
    forwarded_counts = _formal_counts()
    assert forwarded_counts == (2, 1, 2, 2, 2, 2)

    stale_response, stale = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}confirm",
        params={"confirmation_token": old_token},
        csrf_token=csrf_token,
        confirmed=True,
    )
    assert stale_response.status_code == 200
    assert stale.get("outcome") == "failed"
    assert stale.get("response", {}).get("status_code") == 409
    assert _formal_counts() == forwarded_counts

    forward_replay_response, forward_replay = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}confirm",
        params={"confirmation_token": new_token},
        csrf_token=csrf_token,
        confirmed=True,
    )
    assert forward_replay_response.status_code == 200
    assert forward_replay.get("response", {}).get("status_code") == 200
    assert _formal_counts() == forwarded_counts

    _revoked_preview_response, revoked_preview = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}prepare",
        params=params,
        csrf_token=csrf_token,
        confirmed=True,
    )
    revoked_token = _continuation_token(revoked_preview)
    issued_tokens.append(revoked_token)
    _assert_continuation_is_not_rendered(revoked_preview, revoked_token)
    assert len(responses) == 4
    assert _source_counts() == (4, 4)
    assert _formal_counts() == forwarded_counts

    permission = user.user_permissions.get(codename="publish_exchange_calendar")
    user.user_permissions.remove(permission)
    revoked_response, revoked = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}confirm",
        params={"confirmation_token": revoked_token},
        csrf_token=csrf_token,
        confirmed=True,
    )
    assert revoked_response.status_code == 200
    assert revoked.get("outcome") == "failed"
    assert revoked.get("response", {}).get("status_code") == 403
    assert _formal_counts() == forwarded_counts

    current_after_revocation_response, current_after_revocation = _run_tui_action(
        client,
        action_key=f"{_ACTION_PREFIX}current",
        params={"exchange": "SSE"},
        csrf_token=csrf_token,
    )
    assert current_after_revocation_response.status_code == 200
    assert current_after_revocation.get("outcome") == "success"
    assert current_after_revocation["view_model"]["kind"] == "datagrid"
    assert current_after_revocation["view_model"]["status"] == "仅供参考"
    assert _formal_counts() == forwarded_counts

    _assert_continuation_is_not_audited(issued_tokens)
    assert all(session.response.closed for session in responses)


def test_missing_csrf_and_non_session_auth_never_reach_calendar_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outer browser gate rejects missing CSRF and token auth before capture."""

    responses = _install_source(monkeypatch, (_calendar_body(),))
    _install_actual_calendar_runtime(monkeypatch)

    no_csrf_client, no_csrf_user, _proof, no_csrf_token = _publisher_client(
        "calendar-workbench-tui-no-csrf",
        csrf=False,
    )
    assert no_csrf_token is None
    no_csrf_user.is_staff = True
    no_csrf_user.save(update_fields=["is_staff"])
    csrf_denied, _csrf_payload = _run_tui_action(
        no_csrf_client,
        action_key=f"{_ACTION_PREFIX}prepare",
        params={
            "exchange": "SSE",
            "coverage_start": "2026-10-15",
            "coverage_end": "2026-10-16",
        },
        csrf_token=None,
        confirmed=True,
    )
    assert csrf_denied.status_code == 403
    assert responses == []
    assert _source_counts() == (0, 0)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)
    assert TerminalAuditLogORM.objects.count() == 0

    AccountProfileModel.objects.create(
        user=no_csrf_user, display_name="Calendar token fixture", mcp_enabled=True
    )
    _stored_token, raw_token = UserAccessTokenModel.create_token(
        user=no_csrf_user,
        name="calendar-workbench-tui-session-gate",
    )
    token_client = APIClient(enforce_csrf_checks=True)
    path = reverse(
        "api-tui-action-run",
        kwargs={"action_key": f"{_ACTION_PREFIX}prepare"},
    )
    response = cast(
        HttpResponse,
        token_client.post(
            path,
            {
                "params": {
                    "exchange": "SSE",
                    "coverage_start": "2026-10-15",
                    "coverage_end": "2026-10-16",
                },
                "confirmed": True,
            },
            format="json",
            secure=True,
            HTTP_ORIGIN=_ORIGIN,
            HTTP_AUTHORIZATION="Token " + raw_token,
        ),
    )
    token_denied = _json(response, 403)
    assert token_denied.get("error_code") == "tui_session_auth_required"
    assert responses == []
    assert _source_counts() == (0, 0)
    assert _formal_counts() == (0, 0, 0, 0, 0, 0)
    assert TerminalAuditLogORM.objects.count() == 0
