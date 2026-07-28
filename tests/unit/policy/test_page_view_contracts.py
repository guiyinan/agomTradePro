"""Presentation contracts for policy HTML views."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.http import Http404
from django.test import RequestFactory

from apps.policy.interface import page_views


class _PageService:
    def list_rss_sources(self, **kwargs: object) -> list[object]:
        return [kwargs]

    def list_policy_keywords(self, **kwargs: object) -> list[object]:
        return [kwargs]

    def list_rss_fetch_logs(self, **kwargs: object) -> list[object]:
        return [kwargs]

    def get_rss_fetch_log_summary(self, **kwargs: object) -> dict[str, object]:
        return {
            "sources": ["source"],
            "statuses": ["success"],
            "success_count": 3,
            "error_count": 1,
        }

    def list_rss_reader_items(self, **kwargs: object) -> list[object]:
        return [kwargs]

    def get_rss_reader_summary(self, **kwargs: object) -> dict[str, object]:
        return {
            "sources": ["source"],
            "levels": ["P1"],
            "categories": ["gov"],
            "total_items": 5,
            "today_items": 2,
            "p3_items": 1,
        }

    def list_policy_events(self, **kwargs: object) -> list[object]:
        return [kwargs]

    def get_page_constants(self) -> dict[str, object]:
        return {
            "rss_source_categories": ["gov"],
            "policy_levels": ["P1"],
            "event_types": ["rate"],
            "gate_levels": ["open"],
        }

    def create_policy_event(self, payload: dict[str, object]) -> None:
        self.created_event = payload


class _RssService:
    source = SimpleNamespace(id=7)
    keyword = SimpleNamespace(id=8)

    def get_rss_source_config(self, source_id: int):
        return self.source if source_id == 7 else None

    def get_policy_level_keyword(self, keyword_id: int):
        return self.keyword if keyword_id == 8 else None

    def create_rss_source_config(self, payload: dict[str, object]) -> None:
        self.created_source = payload

    def update_rss_source_config(self, source_id: int, payload: dict[str, object]) -> None:
        self.updated_source = (source_id, payload)

    def create_policy_level_keyword(self, payload: dict[str, object]) -> None:
        self.created_keyword = payload

    def update_policy_level_keyword(self, keyword_id: int, payload: dict[str, object]) -> None:
        self.updated_keyword = (keyword_id, payload)


def _view(view_class, path: str):
    view = view_class()
    view.request = RequestFactory().get(path)
    view.kwargs = {}
    view.object_list = []
    return view


def test_policy_list_views_forward_filters_and_build_context(monkeypatch) -> None:
    """List pages forward only selected filters and publish stable summary context."""
    service = _PageService()
    monkeypatch.setattr(page_views, "page_service", service)

    source = _view(
        page_views.RSSSourceListView,
        "/?category=gov&is_active=1&search=bank",
    )
    assert source.get_queryset()[0]["search"] == "bank"
    source_context = source.get_context_data()
    assert source_context["categories"] == ["gov"]
    assert source_context["selected_active"] == "1"

    keyword = _view(page_views.RSSKeywordListView, "/?level=P1&is_active=1")
    assert keyword.get_queryset()[0]["level"] == "P1"
    assert keyword.get_context_data()["selected_level"] == "P1"

    logs = _view(page_views.RSSFetchLogListView, "/?source=7&status=success")
    assert logs.get_queryset()[0]["source_id"] == "7"
    log_context = logs.get_context_data()
    assert log_context["success_count"] == 3
    assert log_context["error_count"] == 1

    reader = _view(page_views.RSSReaderView, "/?source=7&level=P1&category=gov")
    assert reader.get_queryset()[0]["category"] == "gov"
    reader_context = reader.get_context_data()
    assert reader_context["total_items"] == 5
    assert reader_context["p3_items"] == 1

    events = _view(
        page_views.PolicyEventsPageView,
        "/?level=P1&start_date=2026-01-01&end_date=2026-07-24",
    )
    assert events.get_queryset()[0]["end_date"] == "2026-07-24"
    assert events.get_context_data()["selected_start"] == "2026-01-01"

    workbench = _view(page_views.WorkbenchView, "/")
    assert workbench.get_queryset() == []
    context = workbench.get_context_data()
    assert context["event_types"] == ["rate"]
    assert context["gate_levels"] == ["open"]


def test_policy_create_and_update_form_views_delegate_payloads(monkeypatch) -> None:
    """Form views delegate validated payloads and preserve not-found behavior."""
    page_service = _PageService()
    rss_service = _RssService()
    monkeypatch.setattr(page_views, "page_service", page_service)
    monkeypatch.setattr(page_views, "rss_api_service", rss_service)
    monkeypatch.setattr(page_views.messages, "success", lambda *args: None)
    request = RequestFactory().post("/")
    request.user = SimpleNamespace(is_authenticated=True, is_staff=True)
    form = SimpleNamespace(to_payload=lambda: {"name": "contract"})

    create_event = page_views.PolicyEventCreateView()
    create_event.request = request
    assert create_event.form_valid(form).status_code == 302
    assert page_service.created_event == {"name": "contract"}

    create_source = page_views.RSSSourceCreateView()
    create_source.request = request
    assert create_source.form_valid(form).status_code == 302
    assert rss_service.created_source == {"name": "contract"}

    update_source = page_views.RSSSourceUpdateView()
    update_source.request = request
    update_source.source = rss_service.source
    assert update_source.get_form_kwargs()["instance"].id == 7
    assert update_source.form_valid(form).status_code == 302
    assert rss_service.updated_source == (7, {"name": "contract"})

    create_keyword = page_views.PolicyKeywordCreateView()
    create_keyword.request = request
    assert create_keyword.form_valid(form).status_code == 302
    assert rss_service.created_keyword == {"name": "contract"}

    update_keyword = page_views.PolicyKeywordUpdateView()
    update_keyword.request = request
    update_keyword.keyword = rss_service.keyword
    assert update_keyword.get_form_kwargs()["instance"].id == 8
    assert update_keyword.form_valid(form).status_code == 302
    assert rss_service.updated_keyword == (8, {"name": "contract"})

    with pytest.raises(Http404):
        missing_source = page_views.RSSSourceUpdateView()
        missing_source.dispatch(request, source_id=999)
    with pytest.raises(Http404):
        missing_keyword = page_views.PolicyKeywordUpdateView()
        missing_keyword.dispatch(request, keyword_id=999)
