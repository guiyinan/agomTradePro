"""
Interface Layer - URL Configuration for Policy Management

定义政策管理相关的 URL 路由。
"""

from django.urls import path
from django.views.generic import RedirectView

from .page_views import (
    PolicyEventCreateView,
    PolicyEventsPageView,
    PolicyKeywordCreateView,
    PolicyKeywordUpdateView,
    RSSFetchLogListView,
    RSSKeywordListView,
    RSSReaderView,
    RSSSourceCreateView,
    RSSSourceListView,
    RSSSourceUpdateView,
    WorkbenchView,
)

app_name = "policy"

urlpatterns = [
    path("", RedirectView.as_view(url='/policy/workbench/', permanent=False), name="root-redirect"),
    # 工作台页面 (HTML)
    path("workbench/", WorkbenchView.as_view(), name="workbench"),

    # ========== 页面路由 ==========
    path("events/", PolicyEventsPageView.as_view(), name="events-page"),
    path("events/new/", PolicyEventCreateView.as_view(), name="event-create"),
    # RSS 页面（新主路径，避免历史 301 缓存污染）
    path("rss/sources/", RSSSourceListView.as_view(), name="rss-manage"),
    path("rss/sources/new/", RSSSourceCreateView.as_view(), name="rss-source-create"),
    path("rss/sources/<int:source_id>/edit/", RSSSourceUpdateView.as_view(), name="rss-source-edit"),
    path("rss/reader/", RSSReaderView.as_view(), name="rss-reader"),
    path("rss/keywords/", RSSKeywordListView.as_view(), name="rss-keywords"),
    path("rss/keywords/new/", PolicyKeywordCreateView.as_view(), name="rss-keyword-create"),
    path("rss/keywords/<int:keyword_id>/edit/", PolicyKeywordUpdateView.as_view(), name="rss-keyword-edit"),
    path("rss/logs/", RSSFetchLogListView.as_view(), name="rss-logs"),

    # Note: API routes are now handled by api_urls.py mounted at /api/policy/
]
