"""Filter dashboard page boundary tests."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory

from apps.filter.application.use_cases import (
    ApplyFilterResponse,
    GetFilterDataResponse,
)
from apps.filter.domain.entities import FilterResult, FilterSeries, FilterType
from apps.filter.interface import views


def _authenticated_request(query: dict[str, str] | None = None):
    request = RequestFactory().get("/filter/dashboard/", query or {})
    request.user = SimpleNamespace(is_authenticated=True, id=7, pk=7)
    return request


def _capture_render(monkeypatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def _render(request, template_name, context):
        captured["template_name"] = template_name
        captured["context"] = context
        return HttpResponse("ok")

    monkeypatch.setattr(views, "render", _render)
    return captured


def test_filter_dashboard_requires_authentication():
    request = RequestFactory().get("/filter/dashboard/")
    request.user = AnonymousUser()

    response = views.filter_dashboard_view(request)

    assert response.status_code == 302
    assert response.url.startswith("/account/login/")


def test_filter_dashboard_rejects_unknown_filter_type_before_use_case(monkeypatch):
    repository = SimpleNamespace(
        get_available_indicators=lambda: [{"code": "CN_PMI", "name": "PMI"}]
    )
    monkeypatch.setattr(views, "get_filter_repository", lambda: repository)
    captured = _capture_render(monkeypatch)

    response = views.filter_dashboard_view(
        _authenticated_request({"indicator": "CN_PMI", "filter_type": "unknown"})
    )

    assert response.status_code == 200
    assert captured["context"]["error"] == "不支持的滤波器类型。"
    assert captured["context"]["chart_data"] is None


def test_filter_dashboard_fallback_calculation_does_not_persist_on_get(monkeypatch):
    repository = SimpleNamespace(
        get_available_indicators=lambda: [{"code": "CN_PMI", "name": "PMI"}]
    )
    captured_request: dict[str, object] = {}
    series = FilterSeries(
        indicator_code="CN_PMI",
        filter_type=FilterType.HP,
        params={"lamb": 129600.0},
        results=[
            FilterResult(
                date=date(2026, 1, 1),
                original_value=50.0,
                filtered_value=49.8,
                trend=49.8,
            )
        ],
        calculated_at=date(2026, 1, 1),
    )

    class FakeGetUseCase:
        def execute(self, request):
            return GetFilterDataResponse(success=False, error="not found")

    class FakeApplyUseCase:
        def execute(self, request):
            captured_request["request"] = request
            return ApplyFilterResponse(success=True, series=series)

    monkeypatch.setattr(views, "get_filter_repository", lambda: repository)
    monkeypatch.setattr(views, "GetFilterDataUseCase", lambda repo: FakeGetUseCase())
    monkeypatch.setattr(views, "ApplyFilterUseCase", lambda repo: FakeApplyUseCase())
    captured = _capture_render(monkeypatch)

    response = views.filter_dashboard_view(_authenticated_request())

    assert response.status_code == 200
    assert captured_request["request"].save_results is False
    assert captured["context"]["chart_data"]["filtered_values"] == [49.8]


def test_filter_dashboard_redacts_repository_exception(monkeypatch):
    secret = "postgresql://internal-user:secret@database/filter"

    class BrokenRepository:
        def get_available_indicators(self):
            raise RuntimeError(secret)

    monkeypatch.setattr(views, "get_filter_repository", BrokenRepository)
    captured = _capture_render(monkeypatch)

    response = views.filter_dashboard_view(_authenticated_request())

    assert response.status_code == 200
    assert captured["context"]["error"] == "滤波页面暂不可用，请稍后重试。"
    assert secret not in str(captured["context"])


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf")])
def test_filter_chart_rejects_non_finite_values(invalid_value):
    with pytest.raises(ValueError, match="original_values contains invalid values"):
        views._prepare_chart_data(
            dates=["2026-01-01"],
            original_values=[invalid_value],
            filtered_values=[49.8],
            slopes=[None],
        )


def test_filter_chart_rejects_misaligned_series():
    with pytest.raises(ValueError, match="series lengths are inconsistent"):
        views._prepare_chart_data(
            dates=["2026-01-01"],
            original_values=[50.0],
            filtered_values=[],
            slopes=[None],
        )
