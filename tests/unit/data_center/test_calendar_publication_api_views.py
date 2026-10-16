"""HTTP shape tests for calendar publication views with composition stubs."""

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

from apps.data_center.application.calendar_publication_authority import (
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CapturedExchangeCalendarSnapshot,
    ConfirmCalendarPublicationUseCase,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
    CalendarPublicationTransition,
    CurrentPublishedExchangeCalendar,
)
from apps.data_center.interface import calendar_publication_api_views as views
from apps.data_center.interface.calendar_publication_presenters import (
    present_calendar_capture,
    present_calendar_preview,
)
from apps.data_center.interface.calendar_publication_serializers import (
    ConfirmCalendarPublicationInputSerializer,
)
from tests.unit.data_center.test_calendar_publication_operations import (
    CALENDAR_DAY,
    NOW,
    FixedClock,
    Publisher,
    _make_preview,
    _snapshot,
)


class _AuthenticatedUser:
    """Small in-memory principal for APIRequestFactory permission checks."""

    is_authenticated = True
    pk = 11


_USER = _AuthenticatedUser()


def _dispatch(view: object, request: object) -> object:
    """Authenticate a factory request without claiming Session/CSRF coverage."""

    force_authenticate(request, user=_USER)
    return cast(object, view)(request)


def _json_payload(response: object) -> dict[str, object]:
    """Render one JSON response and expose its object payload to assertions."""

    response.render()
    assert response["Content-Type"] == "application/json"
    assert type(response.data) is dict
    return cast(dict[str, object], response.data)


def _capture_receipt() -> CapturedExchangeCalendarSnapshot:
    """Build a valid typed response for the capture presenter."""

    snapshot = _snapshot()
    return CapturedExchangeCalendarSnapshot(
        snapshot_reference=snapshot.reference(),
        first_seen_at=snapshot.first_seen_at,
        recorded_at=snapshot.recorded_at,
        source_published_at=snapshot.source_published_at,
    )


def _formal_commit() -> CalendarFormalPublicationCommit:
    """Build a valid first-publish commit without calling any repository."""

    preview, reader, principal = _make_preview()
    publisher = Publisher()
    return ConfirmCalendarPublicationUseCase(
        preparation=cast(object, reader),
        publisher=cast(object, publisher),
        clock=FixedClock(NOW),
    ).execute(
        preview.confirmation_intent(),
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )


def test_capture_view_uses_typed_intent_and_returns_json_201(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = APIRequestFactory()
    payload = {
        "exchange": "SSE",
        "coverage_start": CALENDAR_DAY.isoformat(),
        "coverage_end": CALENDAR_DAY.isoformat(),
    }
    capture_receipt = _capture_receipt()
    calls: list[tuple[object, object]] = []

    def capture(request: object, intent: object) -> CapturedExchangeCalendarSnapshot:
        calls.append((request, intent))
        return capture_receipt

    monkeypatch.setattr(views, "capture_exchange_calendar_snapshot", capture)
    request = factory.post("/capture/", payload, format="json")
    response = _dispatch(views.CaptureCalendarSnapshotView.as_view(), request)

    assert response.status_code == status.HTTP_201_CREATED
    body = _json_payload(response)
    assert body == {
        "outcome": "success",
        "success": True,
        "data": present_calendar_capture(capture_receipt),
    }
    assert len(calls) == 1
    assert calls[0][1].exchange == "SSE"


def test_preview_view_returns_exact_confirmation_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = APIRequestFactory()
    preview, _reader, _principal = _make_preview()
    calls: list[tuple[object, object]] = []

    def prepare(request: object, intent: object) -> object:
        calls.append((request, intent))
        return preview

    monkeypatch.setattr(views, "preview_calendar_publication", prepare)
    payload = {"snapshot_reference": preview.snapshot_reference.to_payload()}
    request = factory.post("/preview/", payload, format="json")
    response = _dispatch(views.CalendarPublicationPreviewView.as_view(), request)

    assert response.status_code == status.HTTP_200_OK
    body = _json_payload(response)
    assert body["outcome"] == "success"
    assert body["success"] is True
    data = cast(dict[str, object], body["data"])
    assert data == present_calendar_preview(preview)
    echo = ConfirmCalendarPublicationInputSerializer(data=data["confirmation_intent"])
    assert echo.is_valid(), echo.errors
    assert echo.to_intent() == preview.confirmation_intent()
    assert calls[0][1].snapshot_reference == preview.snapshot_reference


@pytest.mark.parametrize(
    ("transition", "expected_status"),
    (
        (CalendarPublicationTransition.FIRST_PUBLISH, status.HTTP_201_CREATED),
        (CalendarPublicationTransition.FORWARD_PUBLISH, status.HTTP_200_OK),
        (CalendarPublicationTransition.EXACT_CURRENT_REPLAY, status.HTTP_200_OK),
    ),
)
def test_confirm_view_returns_contract_status_for_each_transition(
    monkeypatch: pytest.MonkeyPatch,
    transition: CalendarPublicationTransition,
    expected_status: int,
) -> None:
    factory = APIRequestFactory()
    preview, _reader, _principal = _make_preview()
    commit = _formal_commit()
    commit = replace(commit, transition=transition)
    calls: list[tuple[object, object]] = []

    def confirm(request: object, intent: object) -> CalendarFormalPublicationCommit:
        calls.append((request, intent))
        return commit

    monkeypatch.setattr(views, "confirm_calendar_publication", confirm)
    request = factory.post(
        "/confirm/",
        present_calendar_preview(preview)["confirmation_intent"],
        format="json",
    )
    response = _dispatch(views.CalendarPublicationConfirmView.as_view(), request)

    assert response.status_code == expected_status
    body = _json_payload(response)
    assert body["outcome"] == "success"
    assert body["success"] is True
    data = cast(dict[str, object], body["data"])
    assert data["publication_status"] == "published"
    assert len(calls) == 1
    assert calls[0][1] == preview.confirmation_intent()


def test_confirm_view_preserves_core_handler_stale_status_and_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, _reader, _principal = _make_preview()

    def stale(request: object, intent: object) -> CalendarFormalPublicationCommit:
        raise CalendarPublicationOperationsError(
            "stale preview",
            code="CALENDAR_PUBLICATION_POINTER_CHANGED",
            status_code=409,
        )

    monkeypatch.setattr(views, "confirm_calendar_publication", stale)
    request = APIRequestFactory().post(
        "/confirm/",
        present_calendar_preview(preview)["confirmation_intent"],
        format="json",
    )
    response = _dispatch(views.CalendarPublicationConfirmView.as_view(), request)

    assert response.status_code == status.HTTP_409_CONFLICT
    body = _json_payload(response)
    assert body["code"] == "CALENDAR_PUBLICATION_POINTER_CHANGED"


def test_capture_view_maps_session_proof_authentication_error_to_401_json() -> None:
    """The real composition rejects forced auth before any DB-backed authority read."""

    request = APIRequestFactory().post(
        "/capture/",
        {
            "exchange": "SSE",
            "coverage_start": CALENDAR_DAY.isoformat(),
            "coverage_end": CALENDAR_DAY.isoformat(),
        },
        format="json",
    )
    response = _dispatch(views.CaptureCalendarSnapshotView.as_view(), request)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    body = _json_payload(response)
    assert body["code"] == "CALENDAR_PUBLISHER_SESSION_REQUIRED"
    assert body["error"]
    assert "success" not in body


def test_preview_view_preserves_default_application_validation_status_422_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application validation errors keep their default 422 semantics at the API."""

    preview, _reader, _principal = _make_preview()

    def invalid(request: object, intent: object) -> object:
        raise CalendarPublicationOperationsError(
            "invalid calendar publication operation",
            code="CALENDAR_PUBLICATION_OPERATION_INVALID",
        )

    monkeypatch.setattr(views, "preview_calendar_publication", invalid)
    request = APIRequestFactory().post(
        "/preview/",
        {"snapshot_reference": preview.snapshot_reference.to_payload()},
        format="json",
    )
    response = _dispatch(views.CalendarPublicationPreviewView.as_view(), request)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    body = _json_payload(response)
    assert body["code"] == "CALENDAR_PUBLICATION_OPERATION_INVALID"
    assert body["error"] == "invalid calendar publication operation"
    assert "success" not in body


def test_openapi_documents_401_and_422_calendar_error_envelopes() -> None:
    """Every operation documents reachable auth and typed validation failures as JSON."""

    schema = SchemaGenerator(
        patterns=[
            path("api/calendar/capture/", views.CaptureCalendarSnapshotView.as_view()),
            path("api/calendar/preview/", views.CalendarPublicationPreviewView.as_view()),
            path("api/calendar/confirm/", views.CalendarPublicationConfirmView.as_view()),
            path("api/calendar/current/", views.CurrentCalendarView.as_view()),
        ]
    ).get_schema(public=True)

    assert schema is not None
    for path_name, method in (
        ("/api/calendar/capture/", "post"),
        ("/api/calendar/preview/", "post"),
        ("/api/calendar/confirm/", "post"),
        ("/api/calendar/current/", "get"),
    ):
        responses = schema["paths"][path_name][method]["responses"]
        for response_code in ("401", "422"):
            response = responses[response_code]
            assert "application/json" in response["content"]
            response_schema = cast(
                dict[str, object],
                response["content"]["application/json"]["schema"],
            )
            reference = response_schema.get("$ref")
            assert type(reference) is str
            component_name = reference.rsplit("/", 1)[-1]
            component = cast(dict[str, object], schema["components"]["schemas"][component_name])
            properties = cast(dict[str, object], component["properties"])
            assert {"error", "code"} <= properties.keys()


def test_current_view_returns_json_200_and_404_for_absent_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = _formal_commit()
    current = CurrentPublishedExchangeCalendar(
        record=commit.record,
        pointer=commit.pointer,
        as_of=NOW + timedelta(seconds=2),
    )
    calls: list[object] = []

    def read(intent: object) -> CurrentPublishedExchangeCalendar:
        calls.append(intent)
        return current

    monkeypatch.setattr(views, "read_current_exchange_calendar", read)
    request = APIRequestFactory().get(
        "/current/",
        {"dataset_key": commit.record.seal.dataset.value, "exchange": "SSE"},
    )
    response = _dispatch(views.CurrentCalendarView.as_view(), request)

    assert response.status_code == status.HTTP_200_OK
    body = _json_payload(response)
    assert body["outcome"] == "success"
    assert body["success"] is True
    data = cast(dict[str, object], body["data"])
    assert data["publication_status"] == "published"
    assert data["must_not_execute"] is True
    assert len(calls) == 1

    monkeypatch.setattr(views, "read_current_exchange_calendar", lambda intent: None)
    missing_request = APIRequestFactory().get(
        "/current/",
        {"dataset_key": commit.record.seal.dataset.value, "exchange": "SSE"},
    )
    missing = _dispatch(views.CurrentCalendarView.as_view(), missing_request)
    assert missing.status_code == status.HTTP_404_NOT_FOUND
    assert _json_payload(missing)["code"] == "CALENDAR_CURRENT_PUBLICATION_NOT_FOUND"


def test_views_reject_unknown_json_and_query_fields_without_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        views,
        "capture_exchange_calendar_snapshot",
        lambda request, intent: calls.append("capture"),
    )
    factory = APIRequestFactory()
    invalid_post = factory.post(
        "/capture/",
        {
            "exchange": "SSE",
            "coverage_start": CALENDAR_DAY.isoformat(),
            "coverage_end": CALENDAR_DAY.isoformat(),
            "database_alias": "other",
        },
        format="json",
    )
    post_response = _dispatch(views.CaptureCalendarSnapshotView.as_view(), invalid_post)
    assert post_response.status_code == status.HTTP_400_BAD_REQUEST
    assert _json_payload(post_response)["code"] == "VALIDATION_ERROR"

    invalid_get = factory.get(
        "/current/",
        {
            "dataset_key": "tushare.exchange_calendar.raw",
            "exchange": "SSE",
            "as_of": NOW.isoformat(),
        },
    )
    get_response = _dispatch(views.CurrentCalendarView.as_view(), invalid_get)
    assert get_response.status_code == status.HTTP_400_BAD_REQUEST
    assert _json_payload(get_response)["code"] == "VALIDATION_ERROR"
    assert calls == []


def test_confirmation_rejects_nested_extra_fields_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, _reader, _principal = _make_preview()
    payload = present_calendar_preview(preview)["confirmation_intent"]
    assert type(payload) is dict
    pointer = cast(dict[str, object], payload["expected_pointer"])
    pointer["actor_id"] = "django-user:11"
    calls: list[bool] = []
    monkeypatch.setattr(
        views,
        "confirm_calendar_publication",
        lambda request, intent: calls.append(True),
    )
    request = APIRequestFactory().post("/confirm/", payload, format="json")
    response = _dispatch(views.CalendarPublicationConfirmView.as_view(), request)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert _json_payload(response)["code"] == "VALIDATION_ERROR"
    assert calls == []


def test_view_policy_and_negotiation_reject_unauthenticated_wrong_media_and_wrong_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = APIRequestFactory()
    calls: list[bool] = []
    monkeypatch.setattr(
        views,
        "capture_exchange_calendar_snapshot",
        lambda request, intent: calls.append(True),
    )
    payload = {
        "exchange": "SSE",
        "coverage_start": CALENDAR_DAY.isoformat(),
        "coverage_end": CALENDAR_DAY.isoformat(),
    }

    unauthenticated = views.CaptureCalendarSnapshotView.as_view()(
        factory.post("/capture/", payload, format="json")
    )
    assert unauthenticated.status_code == status.HTTP_403_FORBIDDEN
    _json_payload(unauthenticated)

    wrong_media_request = factory.generic(
        "POST",
        "/capture/",
        data=json.dumps(payload).encode("utf-8"),
        content_type="text/plain",
    )
    wrong_media = _dispatch(views.CaptureCalendarSnapshotView.as_view(), wrong_media_request)
    assert wrong_media.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    _json_payload(wrong_media)

    wrong_accept_request = factory.generic(
        "POST",
        "/capture/",
        data=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        HTTP_ACCEPT="text/plain",
    )
    wrong_accept = _dispatch(views.CaptureCalendarSnapshotView.as_view(), wrong_accept_request)
    assert wrong_accept.status_code == status.HTTP_406_NOT_ACCEPTABLE
    _json_payload(wrong_accept)

    wrong_method = _dispatch(
        views.CaptureCalendarSnapshotView.as_view(),
        factory.get("/capture/"),
    )
    assert wrong_method.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    _json_payload(wrong_method)
    assert calls == []


def test_view_classes_are_json_session_authenticated_only() -> None:
    for view_class in (
        views.CaptureCalendarSnapshotView,
        views.CalendarPublicationPreviewView,
        views.CalendarPublicationConfirmView,
        views.CurrentCalendarView,
    ):
        assert len(view_class.authentication_classes) == 1
        assert view_class.authentication_classes[0].__name__ == "SessionAuthentication"
        assert len(view_class.permission_classes) == 1
        assert view_class.permission_classes[0].__name__ == "IsAuthenticated"
        assert [parser.__name__ for parser in view_class.parser_classes] == ["JSONParser"]
        assert [renderer.__name__ for renderer in view_class.renderer_classes] == ["JSONRenderer"]
