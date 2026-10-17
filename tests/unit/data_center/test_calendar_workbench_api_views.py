"""HTTP contracts for the opaque calendar publication workbench API."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from typing import cast

import pytest
from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.data_center.application.calendar_preview_token import CalendarPreviewTokenError
from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CaptureExchangeCalendarSnapshotIntent,
)
from apps.data_center.application.calendar_workbench import CalendarWorkbenchPreview
from apps.data_center.application.calendar_workbench_scope import (
    CalendarWorkbenchCurrentPointerStatus,
    CalendarWorkbenchScopeContext,
    CalendarWorkbenchScopeMetadata,
    CalendarWorkbenchScopeMetadataStatus,
    CalendarWorkbenchSecretRuntimeStatus,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
    CalendarPublicationTransition,
    CurrentPublishedExchangeCalendar,
)
from apps.data_center.calendar_workbench_current_composition import (
    CalendarWorkbenchCurrentReadResult,
)
from apps.data_center.domain.control_plane import CalendarNullableMemberCodecVersion
from apps.data_center.interface import calendar_workbench_api_views as views
from tests.unit.data_center.test_calendar_publication_api_views import _formal_commit
from tests.unit.data_center.test_calendar_publication_operations import NOW
from tests.unit.data_center.test_calendar_workbench import _captured, _preview


class _AuthenticatedUser:
    """Minimal authenticated user for APIRequestFactory view-contract tests."""

    is_authenticated = True
    pk = 11


_USER = _AuthenticatedUser()
_ACTION_KEY = "data-center.calendar-workbench-confirm"
_TOKEN = "encrypted:v1:opaque-calendar-preview-token"


def _dispatch(view: object, request: object) -> object:
    """Authenticate a direct view call without claiming Session/CSRF coverage."""

    force_authenticate(request, user=_USER)
    return cast(object, view)(request)


def _body(response: object) -> dict[str, object]:
    """Render a JSON response and assert its public media contract."""

    response.render()
    assert response["Content-Type"] == "application/json"
    assert type(response.data) is dict
    return cast(dict[str, object], response.data)


def _workbench_preview() -> CalendarWorkbenchPreview:
    """Create exact Application preview data with a test-only opaque token."""

    captured = _captured()
    return CalendarWorkbenchPreview(
        captured=captured,
        preview=_preview(captured),
        confirmation_token=_TOKEN,
    )


def _prepare_payload() -> dict[str, object]:
    """Return only the three user-selectable source-scope fields."""

    return {
        "exchange": "SSE",
        "coverage_start": "2026-10-01",
        "coverage_end": "2026-10-02",
    }


def _selected_scope() -> CalendarWorkbenchScopeContext:
    """Build selected safe metadata with both runtime checks explicitly unchecked."""

    return CalendarWorkbenchScopeContext(
        metadata_status=CalendarWorkbenchScopeMetadataStatus.METADATA_SELECTED,
        metadata=CalendarWorkbenchScopeMetadata(
            dataset_key="tushare.exchange_calendar.raw",
            contract_version="calendar-contract-v1",
            schema_version="exchange-calendar-snapshot-v1",
            calendar_response_max_age_seconds=60,
            policy_identity=f"p2:1:{'5' * 64}",
            policy_version="calendar-policy-v1",
            member_codec_version=CalendarNullableMemberCodecVersion.V1,
            provider_id=7,
            provider="tushare",
            capability="exchange_calendar",
            validator_key="exchange_calendar.tushare.trade_cal.full_date.v1",
        ),
        blocked_reason=None,
        secret_runtime_status=CalendarWorkbenchSecretRuntimeStatus.NOT_CHECKED,
        current_pointer_status=CalendarWorkbenchCurrentPointerStatus.NOT_SCOPED,
        known_at=_workbench_preview().preview.previewed_at,
    )


def _blocked_scope() -> CalendarWorkbenchScopeContext:
    """Build a typed blocked scope with no fabricated selected metadata."""

    result = _selected_scope()
    return replace(
        result,
        metadata_status=CalendarWorkbenchScopeMetadataStatus.BLOCKED,
        metadata=None,
        blocked_reason="CALENDAR_CAPTURE_DATASET_MISSING",
    )


def _current_result(
    *,
    scope: CalendarWorkbenchScopeContext | None = None,
    missing: bool = False,
) -> CalendarWorkbenchCurrentReadResult:
    """Build an exact workbench current result for direct HTTP contract tests."""

    selected_scope = _selected_scope() if scope is None else scope
    commit = _formal_commit()
    current = (
        None
        if missing or selected_scope.metadata_status is CalendarWorkbenchScopeMetadataStatus.BLOCKED
        else CurrentPublishedExchangeCalendar(
            record=commit.record,
            pointer=commit.pointer,
            as_of=NOW + timedelta(seconds=2),
        )
    )
    return CalendarWorkbenchCurrentReadResult(exchange="SSE", scope=selected_scope, current=current)


def test_prepare_returns_safe_summary_and_runtime_only_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hidden token is returned only in the exact TUI handoff envelope."""

    result = _workbench_preview()
    calls: list[tuple[object, object]] = []

    def prepare(request: object, intent: object) -> CalendarWorkbenchPreview:
        calls.append((request, intent))
        return result

    monkeypatch.setattr(views, "prepare_calendar_workbench_preview", prepare)
    request = APIRequestFactory().post("/prepare/", _prepare_payload(), format="json")
    response = _dispatch(views.CalendarWorkbenchPrepareView.as_view(), request)

    assert response.status_code == status.HTTP_201_CREATED
    body = _body(response)
    assert set(body) == {"outcome", "success", "data", "continuation"}
    assert body["outcome"] == "success"
    assert body["success"] is True
    data = cast(dict[str, object], body["data"])
    assert data["publication_status"] == "preview"
    assert data["exchange"] == "SSE"
    assert data["coverage_start"] == "2026-10-01"
    assert data["coverage_end"] == "2026-10-02"
    assert data["must_not_execute"] is True
    assert data["must_not_use_for_decision"] is True
    assert cast(dict[str, object], data["freshness"])["source_observed_at"] is None
    assert "confirmation_token" not in data
    assert "confirmation_intent" not in data
    assert "preview_hash" not in data
    assert "expected_publication_hash" not in data
    assert "snapshot_reference" not in data
    assert _TOKEN not in json.dumps(data, ensure_ascii=False)
    assert body["continuation"] == {
        "action_key": _ACTION_KEY,
        "input": {"confirmation_token": _TOKEN},
        "expires_at": result.preview.response_expires_at.isoformat().replace("+00:00", "Z"),
    }
    assert len(calls) == 1
    assert calls[0][1] == CaptureExchangeCalendarSnapshotIntent(
        exchange="SSE",
        coverage_start=result.captured.snapshot_reference.coverage_start,
        coverage_end=result.captured.snapshot_reference.coverage_end,
    )
    assert calls[0][0]._request is request


@pytest.mark.parametrize(
    "extra_field",
    (
        "actor_id",
        "user_id",
        "database_alias",
        "as_of",
        "known_at",
        "calendar_response_max_age_seconds",
        "ttl",
        "publication_hash",
    ),
)
def test_prepare_rejects_client_authority_clock_ttl_and_hash_fields(
    monkeypatch: pytest.MonkeyPatch,
    extra_field: str,
) -> None:
    """Only scope is client input; metadata and authorization are server-owned."""

    calls: list[bool] = []
    monkeypatch.setattr(
        views,
        "prepare_calendar_workbench_preview",
        lambda request, intent: calls.append(True),
    )
    payload = _prepare_payload()
    payload[extra_field] = "must-not-be-accepted"
    request = APIRequestFactory().post("/prepare/", payload, format="json")
    response = _dispatch(views.CalendarWorkbenchPrepareView.as_view(), request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    body = _body(response)
    assert body["code"] == "VALIDATION_ERROR"
    assert "不支持" in json.dumps(body, ensure_ascii=False)
    assert calls == []


@pytest.mark.parametrize(
    "payload",
    (
        {"exchange": "SSE", "coverage_start": "2026-10-02", "coverage_end": "2026-10-01"},
        {"exchange": " SSE", "coverage_start": "2026-10-01", "coverage_end": "2026-10-02"},
        {"exchange": "SSE", "coverage_start": "2026-10-01T00:00:00Z", "coverage_end": "2026-10-02"},
        {"exchange": 1, "coverage_start": "2026-10-01", "coverage_end": "2026-10-02"},
    ),
)
def test_prepare_rejects_noncanonical_dates_ranges_and_coercible_values(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    """The serializer rejects malformed dates and values before owner access."""

    calls: list[bool] = []
    monkeypatch.setattr(
        views,
        "prepare_calendar_workbench_preview",
        lambda request, intent: calls.append(True),
    )
    request = APIRequestFactory().post("/prepare/", payload, format="json")
    response = _dispatch(views.CalendarWorkbenchPrepareView.as_view(), request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in _body(response)
    assert calls == []


@pytest.mark.parametrize(
    ("transition", "expected_status"),
    (
        (CalendarPublicationTransition.FIRST_PUBLISH, status.HTTP_201_CREATED),
        (CalendarPublicationTransition.FORWARD_PUBLISH, status.HTTP_200_OK),
        (CalendarPublicationTransition.EXACT_CURRENT_REPLAY, status.HTTP_200_OK),
    ),
)
def test_confirm_accepts_only_token_and_returns_safe_publication_summary(
    monkeypatch: pytest.MonkeyPatch,
    transition: CalendarPublicationTransition,
    expected_status: int,
) -> None:
    """Confirmation response omits token, hashes, seal, raw source and Audit data."""

    commit = replace(_formal_commit(), transition=transition)
    calls: list[tuple[object, object]] = []

    def confirm(request: object, token: str) -> CalendarFormalPublicationCommit:
        calls.append((request, token))
        return commit

    monkeypatch.setattr(views, "confirm_calendar_workbench_preview", confirm)
    request = APIRequestFactory().post(
        "/confirm/",
        {"confirmation_token": _TOKEN},
        format="json",
    )
    response = _dispatch(views.CalendarWorkbenchConfirmView.as_view(), request)

    assert response.status_code == expected_status
    body = _body(response)
    assert set(body) == {"outcome", "success", "data"}
    assert body["outcome"] == "success"
    assert body["success"] is True
    data = cast(dict[str, object], body["data"])
    assert data["publication_status"] == "published"
    assert data["transition_label"]
    assert data["must_not_execute"] is True
    assert data["must_not_use_for_decision"] is True
    assert "publication_hash" not in data
    assert "publication_id" not in data
    assert "activation_id" not in data
    assert "audit_pair" not in data
    assert "seal" not in data
    assert _TOKEN not in json.dumps(body, ensure_ascii=False)
    assert len(calls) == 1
    assert calls[0][0]._request is request
    assert calls[0][1] == _TOKEN


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"confirmation_token": ""},
        {"confirmation_token": False},
        {"confirmation_token": _TOKEN, "actor_id": "django-user:11"},
        {"confirmation_token": _TOKEN, "database_alias": "default"},
        {"confirmation_token": _TOKEN, "as_of": "2026-10-17T08:00:00Z"},
        {"confirmation_token": _TOKEN, "confirmation_intent": {"preview_hash": "x"}},
    ),
)
def test_confirm_rejects_missing_or_extra_fields_without_owner_call(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    """The opaque token is the sole confirmation input."""

    calls: list[bool] = []
    monkeypatch.setattr(
        views,
        "confirm_calendar_workbench_preview",
        lambda request, token: calls.append(True),
    )
    request = APIRequestFactory().post("/confirm/", payload, format="json")
    response = _dispatch(views.CalendarWorkbenchConfirmView.as_view(), request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in _body(response)
    assert calls == []


@pytest.mark.parametrize(
    ("error", "expected_status", "message_fragment"),
    (
        (
            CalendarPreviewTokenError(
                "private token failure detail",
                code="CALENDAR_PREVIEW_TOKEN_EXPIRED",
                status_code=409,
            ),
            status.HTTP_409_CONFLICT,
            "预览已过期",
        ),
        (
            CalendarPublicationOperationsError(
                "private CAS failure detail",
                code="CALENDAR_PUBLICATION_POINTER_CHANGED",
                status_code=409,
            ),
            status.HTTP_409_CONFLICT,
            "发布条件已变化",
        ),
    ),
)
def test_confirm_returns_actionable_chinese_conflict_without_internal_detail(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    message_fragment: str,
) -> None:
    """Stable error codes remain actionable without leaking internals or token."""

    def fail(request: object, token: str) -> CalendarFormalPublicationCommit:
        raise error

    monkeypatch.setattr(views, "confirm_calendar_workbench_preview", fail)
    request = APIRequestFactory().post(
        "/confirm/",
        {"confirmation_token": _TOKEN},
        format="json",
    )
    response = _dispatch(views.CalendarWorkbenchConfirmView.as_view(), request)

    assert response.status_code == expected_status
    body = _body(response)
    assert body["code"] == error.code  # type: ignore[attr-defined]
    assert message_fragment in cast(str, body["error"])
    assert "private" not in json.dumps(body, ensure_ascii=False)
    assert _TOKEN not in json.dumps(body, ensure_ascii=False)


def test_workbench_views_keep_session_json_and_method_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new endpoints retain SessionAuthentication and JSON-only behavior."""

    monkeypatch.setattr(
        views,
        "prepare_calendar_workbench_preview",
        lambda request, intent: _workbench_preview(),
    )
    factory = APIRequestFactory()
    payload = _prepare_payload()

    anonymous = views.CalendarWorkbenchPrepareView.as_view()(
        factory.post("/prepare/", payload, format="json")
    )
    assert anonymous.status_code == status.HTTP_403_FORBIDDEN
    _body(anonymous)

    wrong_media_request = factory.generic(
        "POST",
        "/prepare/",
        data=json.dumps(payload).encode("utf-8"),
        content_type="text/plain",
    )
    wrong_media = _dispatch(views.CalendarWorkbenchPrepareView.as_view(), wrong_media_request)
    assert wrong_media.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    _body(wrong_media)

    wrong_accept_request = factory.generic(
        "POST",
        "/prepare/",
        data=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        HTTP_ACCEPT="text/plain",
    )
    wrong_accept = _dispatch(views.CalendarWorkbenchPrepareView.as_view(), wrong_accept_request)
    assert wrong_accept.status_code == status.HTTP_406_NOT_ACCEPTABLE
    _body(wrong_accept)

    wrong_method = _dispatch(
        views.CalendarWorkbenchConfirmView.as_view(),
        factory.get("/confirm/"),
    )
    assert wrong_method.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    _body(wrong_method)


@pytest.mark.parametrize(
    ("scope", "expected_status"),
    (
        (_selected_scope(), "metadata_selected"),
        (_blocked_scope(), "blocked"),
    ),
)
def test_scope_view_returns_only_selected_or_blocked_configuration_metadata(
    monkeypatch: pytest.MonkeyPatch,
    scope: CalendarWorkbenchScopeContext,
    expected_status: str,
) -> None:
    """The authenticated scope read does not require publish permission or runtime IO."""

    calls: list[bool] = []

    def read_scope() -> CalendarWorkbenchScopeContext:
        calls.append(True)
        return scope

    monkeypatch.setattr(views, "read_calendar_workbench_scope_context", read_scope)
    request = APIRequestFactory().get("/scope/")
    response = _dispatch(views.CalendarWorkbenchScopeView.as_view(), request)

    assert response.status_code == status.HTTP_200_OK
    body = _body(response)
    assert body["outcome"] == "success"
    data = cast(dict[str, object], body["data"])
    assert data["metadata_status"] == expected_status
    assert data["secret_runtime_status"] == "not_checked"
    assert data["current_pointer_status"] == "not_scoped"
    assert data["known_at"]
    assert len(calls) == 1
    metadata = data["metadata"]
    if expected_status == "metadata_selected":
        assert type(metadata) is dict
        assert cast(dict[str, object], metadata)["dataset_key"] == "tushare.exchange_calendar.raw"
        assert "token" not in json.dumps(metadata).lower()
    else:
        assert metadata is None
        assert data["blocked_reason"] == "CALENDAR_CAPTURE_DATASET_MISSING"


@pytest.mark.parametrize(
    "query",
    (
        {"dataset_key": "tushare.exchange_calendar.raw"},
        {"exchange": "SSE"},
        {"as_of": "2026-10-17T08:00:00Z"},
    ),
)
def test_scope_view_rejects_client_selected_scope_or_clock(
    monkeypatch: pytest.MonkeyPatch,
    query: dict[str, str],
) -> None:
    """Scope metadata is global and server-selected; clients provide no defaults."""

    calls: list[bool] = []
    monkeypatch.setattr(
        views,
        "read_calendar_workbench_scope_context",
        lambda: calls.append(True),
    )
    request = APIRequestFactory().get("/scope/", query)
    response = _dispatch(views.CalendarWorkbenchScopeView.as_view(), request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in _body(response)
    assert calls == []


def test_current_view_accepts_only_exchange_and_returns_reference_only_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The workbench chooses the dataset and presents only non-execution data."""

    result = _current_result()
    calls: list[str] = []
    monkeypatch.setattr(
        views,
        "read_calendar_workbench_current",
        lambda exchange: calls.append(exchange) or result,
    )
    request = APIRequestFactory().get("/current/", {"exchange": "SSE"})
    response = _dispatch(views.CalendarWorkbenchCurrentView.as_view(), request)

    assert response.status_code == status.HTTP_200_OK
    body = _body(response)
    assert set(body) == {"outcome", "success", "data"}
    data = cast(dict[str, object], body["data"])
    assert data["configuration_status"] == "metadata_selected"
    assert data["current_status"] == "published"
    assert data["blocked_reason"] is None
    current = cast(dict[str, object], data["current"])
    assert current["exchange"] == "SSE"
    assert current["must_not_execute"] is True
    assert current["must_not_use_for_decision"] is True
    assert cast(dict[str, object], current["freshness"])["source_observed_at"] is None
    assert "publication_id" not in current
    assert "publication_hash" not in current
    assert "activation_id" not in current
    assert "dataset_key" not in current
    assert calls == ["SSE"]


def test_current_view_preserves_original_publication_expiry_after_config_ttl_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newly selected config TTL cannot extend or shorten an old publication window."""

    original_scope = _selected_scope()
    assert original_scope.metadata is not None
    changed_scope = replace(
        original_scope,
        metadata=replace(
            original_scope.metadata,
            calendar_response_max_age_seconds=1,
        ),
    )
    result = _current_result(scope=changed_scope)
    assert result.current is not None
    original_expiry = result.current.record.window.response_expires_at
    new_config_expiry = result.current.record.seal.snapshot_first_seen_at + timedelta(
        seconds=changed_scope.metadata.calendar_response_max_age_seconds
    )
    assert original_expiry != new_config_expiry

    monkeypatch.setattr(views, "read_calendar_workbench_current", lambda exchange: result)
    request = APIRequestFactory().get("/current/", {"exchange": "SSE"})
    response = _dispatch(views.CalendarWorkbenchCurrentView.as_view(), request)

    assert response.status_code == status.HTTP_200_OK
    data = cast(dict[str, object], _body(response)["data"])
    current = cast(dict[str, object], data["current"])
    assert current["response_expires_at"] == original_expiry.isoformat().replace("+00:00", "Z")
    assert current["response_expires_at"] != new_config_expiry.isoformat().replace("+00:00", "Z")


def test_current_view_preserves_blocked_configuration_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid or absent scope blocks current lookup with its exact selector reason."""

    scope = _blocked_scope()
    result = _current_result(scope=scope)
    calls: list[str] = []
    monkeypatch.setattr(
        views,
        "read_calendar_workbench_current",
        lambda exchange: calls.append(exchange) or result,
    )
    request = APIRequestFactory().get("/current/", {"exchange": "SSE"})
    response = _dispatch(views.CalendarWorkbenchCurrentView.as_view(), request)

    assert response.status_code == status.HTTP_200_OK
    data = cast(dict[str, object], _body(response)["data"])
    assert data["configuration_status"] == "blocked"
    assert data["current_status"] == "blocked"
    assert data["blocked_reason"] == scope.blocked_reason
    assert data["current"] is None
    assert calls == ["SSE"]


def test_current_view_reports_missing_current_without_historical_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty exact current pointer is explicit, with no old-publication fallback."""

    result = _current_result(missing=True)
    monkeypatch.setattr(views, "read_calendar_workbench_current", lambda exchange: result)
    request = APIRequestFactory().get("/current/", {"exchange": "SSE"})
    response = _dispatch(views.CalendarWorkbenchCurrentView.as_view(), request)

    assert response.status_code == status.HTTP_200_OK
    data = cast(dict[str, object], _body(response)["data"])
    assert data["configuration_status"] == "metadata_selected"
    assert data["current_status"] == "not_found"
    assert data["blocked_reason"] == "CALENDAR_CURRENT_PUBLICATION_NOT_FOUND"
    assert data["current"] is None


@pytest.mark.parametrize(
    "query",
    (
        {"exchange": "SSE", "dataset_key": "tushare.exchange_calendar.raw"},
        {"exchange": "SSE", "database_alias": "default"},
        {"exchange": "SSE", "as_of": "2026-10-17T00:00:00Z"},
        {"exchange": "SSE", "actor_id": "django-user:11"},
        {"exchange": "SSE", "user_id": "11"},
        {"exchange": " SSE"},
    ),
)
def test_current_view_rejects_client_dataset_alias_clock_and_noncanonical_exchange(
    monkeypatch: pytest.MonkeyPatch,
    query: dict[str, str],
) -> None:
    """The only accepted caller-selected field is one exact exchange token."""

    calls: list[str] = []
    monkeypatch.setattr(
        views,
        "read_calendar_workbench_current",
        lambda exchange: calls.append(exchange),
    )
    request = APIRequestFactory().get("/current/", query)
    response = _dispatch(views.CalendarWorkbenchCurrentView.as_view(), request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in _body(response)
    assert calls == []


@pytest.mark.parametrize(
    "query_string",
    (
        "/current/?exchange=SSE&exchange=SSE",
        "/current/?exchange=SSE&exchange=SZSE",
    ),
)
def test_current_view_rejects_repeated_exchange_query_parameter(
    monkeypatch: pytest.MonkeyPatch,
    query_string: str,
) -> None:
    """Duplicate query values are rejected even when the duplicate is identical."""

    calls: list[str] = []
    monkeypatch.setattr(
        views,
        "read_calendar_workbench_current",
        lambda exchange: calls.append(exchange),
    )
    request = APIRequestFactory().get(query_string)
    response = _dispatch(views.CalendarWorkbenchCurrentView.as_view(), request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in _body(response)
    assert calls == []


def test_openapi_marks_continuation_and_token_as_tui_hidden() -> None:
    """Schema exposes transport shape while clearly marking opaque values hidden."""

    prepare_view = views.CalendarWorkbenchPrepareView.as_view()
    confirm_view = views.CalendarWorkbenchConfirmView.as_view()
    current_view = views.CalendarWorkbenchCurrentView.as_view()
    schema = SchemaGenerator(
        patterns=[
            path("api/data-center/calendar/workbench/prepare/", prepare_view),
            path("api/data-center/calendar/workbench/confirm/", confirm_view),
            path(
                "api/data-center/calendar/workbench/scope/",
                views.CalendarWorkbenchScopeView.as_view(),
            ),
            path("api/data-center/calendar/workbench/current/", current_view),
        ]
    ).get_schema(public=True)

    assert schema is not None
    prepare_response = schema["paths"]["/api/data-center/calendar/workbench/prepare/"]["post"]
    prepare_responses = cast(dict[str, object], prepare_response["responses"])
    assert "201" in prepare_responses
    prepare_response_contract = cast(dict[str, object], prepare_responses["201"])
    prepare_content = cast(dict[str, object], prepare_response_contract["content"])
    prepare_json = cast(dict[str, object], prepare_content["application/json"])
    continuation_ref = _schema_ref(prepare_json["schema"])
    prepare_component = _schema_component(schema, continuation_ref)
    prepare_properties = cast(dict[str, object], prepare_component["properties"])
    response_data = _schema_component(schema, _schema_ref(prepare_properties["data"]))
    response_data_properties = cast(dict[str, object], response_data["properties"])
    assert "confirmation_token" not in response_data_properties
    assert "preview_hash" not in response_data_properties
    continuation_schema = _schema_component(schema, _schema_ref(prepare_properties["continuation"]))
    assert continuation_schema["x-tui-hidden"] is True

    confirm_operation = schema["paths"]["/api/data-center/calendar/workbench/confirm/"]["post"]
    request_content = cast(
        dict[str, object],
        cast(dict[str, object], confirm_operation["requestBody"])["content"],
    )
    request_schema = _schema_component(
        schema,
        _schema_ref(cast(dict[str, object], request_content["application/json"])["schema"]),
    )
    request_properties = cast(dict[str, object], request_schema["properties"])
    token_schema = _schema_node(schema, request_properties["confirmation_token"])
    assert token_schema["x-tui-hidden"] is True
    assert token_schema["writeOnly"] is True

    scope_operation = schema["paths"]["/api/data-center/calendar/workbench/scope/"]["get"]
    assert "parameters" not in scope_operation or scope_operation["parameters"] == []
    assert "requestBody" not in scope_operation
    assert "200" in cast(dict[str, object], scope_operation["responses"])

    current_operation = schema["paths"]["/api/data-center/calendar/workbench/current/"]["get"]
    parameters = cast(list[dict[str, object]], current_operation["parameters"])
    assert len(parameters) == 1
    assert parameters[0]["name"] == "exchange"
    assert parameters[0]["in"] == "query"


def _schema_ref(value: object) -> str:
    """Read a JSON reference from a schema node."""

    assert type(value) is dict
    reference = cast(dict[str, object], value).get("$ref")
    assert type(reference) is str
    return reference.rsplit("/", 1)[-1]


def _schema_node(schema: dict[str, object], value: object) -> dict[str, object]:
    """Resolve either an inline schema or a component reference."""

    assert type(value) is dict
    node = cast(dict[str, object], value)
    if "$ref" not in node:
        return node
    return _schema_component(schema, _schema_ref(value))


def _schema_component(schema: dict[str, object], name: str) -> dict[str, object]:
    """Return one named OpenAPI component."""

    components = cast(dict[str, object], schema["components"])
    schemas = cast(dict[str, object], components["schemas"])
    return cast(dict[str, object], schemas[name])
