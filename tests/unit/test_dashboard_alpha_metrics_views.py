"""Dashboard Alpha metrics interface contract tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from django.test import RequestFactory

from apps.dashboard.application.queries import AlphaVisualizationData
from apps.dashboard.interface import alpha_metrics_views
from apps.dashboard.interface.dashboard_alpha_context import _as_json_object


def test_alpha_metrics_data_returns_mapping_contract():
    class FakeQuery:
        def execute_metrics(self, ic_days: int = 30) -> AlphaVisualizationData:
            return AlphaVisualizationData(
                stock_scores=[],
                stock_scores_meta={},
                provider_status={
                    "status": "available",
                    "data_source": "live",
                    "providers": {"qlib": {"status": "healthy"}},
                },
                coverage_metrics={
                    "status": "available",
                    "data_source": "live",
                    "coverage_ratio": 0.8,
                },
                ic_trends=[{"date": "2026-07-25", "ic": 0.12}],
                ic_trends_meta={"status": "available", "data_source": "live"},
            )

    payload = alpha_metrics_views.get_alpha_metrics_data(query_factory=FakeQuery)

    context_payload = _as_json_object(payload)

    assert payload.provider_status["providers"]["qlib"]["status"] == "healthy"
    assert payload.coverage_metrics["coverage_ratio"] == 0.8
    assert payload.ic_trends == [{"date": "2026-07-25", "ic": 0.12}]
    assert context_payload["provider_status"] == payload.provider_status


def test_alpha_metrics_data_fails_closed_for_malformed_payload():
    class MalformedQuery:
        def execute_metrics(self, ic_days: int = 30):
            return SimpleNamespace(
                stock_scores=[],
                stock_scores_meta={},
                provider_status=["not", "a", "mapping"],
                coverage_metrics={},
                ic_trends=["not-a-row"],
                ic_trends_meta={},
            )

    payload = alpha_metrics_views.get_alpha_metrics_data(query_factory=MalformedQuery)

    assert payload.provider_status["status"] == "degraded"
    assert payload.coverage_metrics["status"] == "degraded"
    assert payload.ic_trends == []
    assert payload.ic_trends_meta["status"] == "degraded"


def test_alpha_ic_trends_rejects_unbounded_days():
    request = RequestFactory().get("/api/dashboard/alpha/ic-trends/", {"days": "3651"})
    request.user = SimpleNamespace(
        id=7,
        pk=7,
        is_authenticated=True,
        is_active=True,
        username="admin",
    )

    response = alpha_metrics_views.alpha_ic_trends_htmx(request)
    if hasattr(response, "render") and not getattr(response, "is_rendered", True):
        response.render()
    payload = json.loads(response.content)

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"] == "days must not exceed 3650"
