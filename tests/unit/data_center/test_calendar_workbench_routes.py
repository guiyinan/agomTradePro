"""Production URL and discovery contracts for calendar workbench operations."""

from __future__ import annotations

import pytest
from django.urls import resolve, reverse
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.data_center.interface.api_urls import DataCenterApiRootView
from apps.data_center.interface.calendar_workbench_api_views import (
    CalendarWorkbenchConfirmView,
    CalendarWorkbenchCurrentView,
    CalendarWorkbenchPrepareView,
    CalendarWorkbenchScopeView,
)


@pytest.mark.parametrize(
    ("operation", "view"),
    [
        ("scope", CalendarWorkbenchScopeView),
        ("current", CalendarWorkbenchCurrentView),
        ("prepare", CalendarWorkbenchPrepareView),
        ("confirm", CalendarWorkbenchConfirmView),
    ],
)
def test_workbench_routes_bind_the_exact_owner_view(operation: str, view: type[APIView]) -> None:
    """Resolve real root URLs and reverse their stable public names."""

    url = f"/api/data-center/exchange-calendars/workbench/{operation}/"
    match = resolve(url)
    assert match.func.view_class is view
    assert match.url_name == f"dc-calendar-workbench-{operation}"
    assert match.namespace == "api_data_center"
    assert reverse(f"api_data_center:{match.url_name}") == url


def test_data_center_root_lists_the_four_workbench_operations() -> None:
    """Keep discovery links synchronized without claiming authentication coverage."""

    request = Request(APIRequestFactory().get("/api/data-center/"))
    response = DataCenterApiRootView().get(request)
    response.accepted_renderer = CalendarWorkbenchScopeView.renderer_classes[0]()
    response.accepted_media_type = "application/json"
    response.renderer_context = {}
    response.render()
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    for operation in ("scope", "current", "prepare", "confirm"):
        assert response.data["endpoints"][f"exchange_calendar_workbench_{operation}"] == (
            f"/api/data-center/exchange-calendars/workbench/{operation}/"
        )
