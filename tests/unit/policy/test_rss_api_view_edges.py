"""Low-level RSS API lookup and task-dispatch contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rest_framework.exceptions import NotFound

from apps.policy.interface import rss_api_views


class _Service:
    source = SimpleNamespace(id=7, name="NBS", category="gov")
    log = SimpleNamespace(id=9)
    keyword = SimpleNamespace(id=11)

    def list_rss_source_configs(self, **kwargs: object):
        return [kwargs]

    def get_rss_source_config(self, source_id: int):
        return self.source if source_id == 7 else None

    def list_rss_fetch_logs(self, **kwargs: object):
        return [kwargs]

    def get_rss_fetch_log(self, log_id: int):
        return self.log if log_id == 9 else None

    def list_policy_level_keywords(self, **kwargs: object):
        return [kwargs]

    def get_policy_level_keyword(self, keyword_id: int):
        return self.keyword if keyword_id == 11 else None


def _bind(view, query: dict[str, str], pk: object = None) -> None:
    view.request = SimpleNamespace(query_params=query)
    view.kwargs = {"pk": pk}
    view.check_object_permissions = lambda request, obj: None


def test_rss_source_log_and_keyword_lookup_boundaries(monkeypatch) -> None:
    """ViewSets parse identifiers, forward filters, and map absent rows to 404."""
    service = _Service()
    monkeypatch.setattr(rss_api_views, "rss_api_service", service)

    sources = rss_api_views.RSSSourceConfigViewSet()
    _bind(
        sources,
        {"category": "gov", "is_active": "1", "parser_type": "feedparser", "search": "NBS"},
        7,
    )
    assert sources.get_queryset()[0]["search"] == "NBS"
    assert sources.get_object().id == 7
    sources.kwargs = {"pk": "bad"}
    with pytest.raises(NotFound):
        sources.get_object()
    sources.kwargs = {"pk": 8}
    with pytest.raises(NotFound):
        sources.get_object()
    sources.action = "create"
    assert sources.get_serializer_class() is rss_api_views.RSSSourceConfigCreateSerializer
    sources.action = "list"
    assert sources.get_serializer_class() is rss_api_views.RSSSourceConfigSerializer

    logs = rss_api_views.RSSFetchLogViewSet()
    _bind(logs, {"source__name": "NBS", "source": "7", "status": "success"}, 9)
    assert logs.get_queryset()[0]["source_name"] == "NBS"
    assert logs.get_object().id == 9
    logs.kwargs = {"pk": None}
    with pytest.raises(NotFound):
        logs.get_object()

    keywords = rss_api_views.PolicyLevelKeywordViewSet()
    _bind(keywords, {"level": "P1", "is_active": "1", "category": "growth"}, 11)
    assert keywords.get_queryset()[0]["category"] == "growth"
    assert keywords.get_object().id == 11
    keywords.kwargs = {"pk": 12}
    with pytest.raises(NotFound):
        keywords.get_object()


def test_rss_trigger_fetch_synchronous_success_and_failure(monkeypatch) -> None:
    """Eager-mode manual fetches expose completed results and provider failures."""
    from django.conf import settings

    from apps.policy.application import tasks

    monkeypatch.setattr(settings, "CELERY_TASK_ALWAYS_EAGER", True)
    source = SimpleNamespace(id=7, name="NBS")
    view = rss_api_views.RSSSourceConfigViewSet()
    view.get_object = lambda: source
    request = SimpleNamespace(data={})
    monkeypatch.setattr(
        tasks,
        "fetch_rss_sources",
        lambda source_id: {"fetched": 3, "source_id": source_id},
    )
    completed = view.trigger_fetch(request, pk=7)
    assert completed.status_code == 200
    assert completed.data["status"] == "completed"
    assert completed.data["result"]["fetched"] == 3

    def _fail(source_id: int):
        raise RuntimeError("feed unavailable")

    monkeypatch.setattr(tasks, "fetch_rss_sources", _fail)
    failed = view.trigger_fetch(request, pk=7)
    assert failed.status_code == 500
    assert "feed unavailable" in failed.data["error"]

    monkeypatch.setattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)

    class _Task:
        @staticmethod
        def delay(**kwargs: object):
            return SimpleNamespace(id="task-7")

    tracked: list[dict[str, object]] = []
    monkeypatch.setattr(tasks, "fetch_rss_sources", _Task())
    monkeypatch.setattr(
        rss_api_views,
        "record_pending_task",
        lambda **kwargs: tracked.append(kwargs),
    )
    queued = view.trigger_fetch(request, pk=7)
    assert queued.data["status"] == "triggered"
    assert queued.data["task_id"] == "task-7"
    assert tracked[0]["kwargs"] == {"source_id": 7}

    all_result = view.fetch_all(SimpleNamespace(data={"source_id": 7}))
    assert all_result.data == {"status": "triggered", "task_id": "task-7"}
    assert tracked[-1]["kwargs"] == {"source_id": 7}

    class _BrokenTask:
        @staticmethod
        def delay(**kwargs: object):
            raise RuntimeError("broker offline")

    monkeypatch.setattr(tasks, "fetch_rss_sources", _BrokenTask())
    unavailable = view.trigger_fetch(request, pk=7)
    assert unavailable.status_code == 503
    assert "broker offline" in unavailable.data["error"]
