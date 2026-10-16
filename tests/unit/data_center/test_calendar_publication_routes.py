"""The calendar workflow must be mounted in the real canonical API tree."""

from __future__ import annotations

from typing import cast

import pytest
from django.urls import Resolver404, resolve, reverse
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.data_center.interface.api_urls import DataCenterApiRootView
from apps.data_center.interface.calendar_publication_api_views import (
    CalendarPublicationConfirmView,
    CalendarPublicationPreviewView,
    CaptureCalendarSnapshotView,
    CurrentCalendarView,
)

_ROUTES: tuple[tuple[str, type[APIView], str, str], ...] = (
    (
        "/api/data-center/exchange-calendars/snapshots/capture/",
        CaptureCalendarSnapshotView,
        "dc-calendar-capture",
        "exchange_calendar_capture",
    ),
    (
        "/api/data-center/exchange-calendars/publication-preview/",
        CalendarPublicationPreviewView,
        "dc-calendar-preview",
        "exchange_calendar_preview",
    ),
    (
        "/api/data-center/exchange-calendars/publications/",
        CalendarPublicationConfirmView,
        "dc-calendar-publish",
        "exchange_calendar_publish",
    ),
    (
        "/api/data-center/exchange-calendars/current/",
        CurrentCalendarView,
        "dc-calendar-current",
        "exchange_calendar_current",
    ),
)


@pytest.mark.parametrize(("path", "view", "name", "_key"), _ROUTES)
def test_calendar_operation_route_uses_the_real_session_only_view(
    path: str, view: type[APIView], name: str, _key: str
) -> None:
    try:
        match = resolve(path)
    except Resolver404:
        pytest.fail(f"Calendar operation is not mounted: {path}", pytrace=False)
    assert getattr(match.func, "cls", None) is view
    assert match.namespace == "api_data_center"
    assert reverse(f"api_data_center:{name}") == path
    assert view.authentication_classes == (SessionAuthentication,)
    assert view.permission_classes == (IsAuthenticated,)


def test_data_center_root_discovers_all_calendar_workflow_steps() -> None:
    request = Request(APIRequestFactory().get("/api/data-center/"))
    response = DataCenterApiRootView().get(request)
    endpoints = cast(dict[str, str], response.data["endpoints"])
    for path, _view, _name, key in _ROUTES:
        assert endpoints.get(key) == path
