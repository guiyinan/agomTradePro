"""
Interface Layer - URL Configuration for Policy Management

定义政策管理相关的 URL 路由。
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PolicyStatusView,
    PolicyEventListView,
    PolicyEventDetailView,
    PolicyEventsPageView,
    RSSSourceConfigViewSet,
    RSSFetchLogViewSet,
    PolicyLevelKeywordViewSet,
    RSSSourceListView,
    RSSKeywordListView,
    RSSFetchLogListView,
    RSSReaderView,
    AuditQueueView,
    ReviewPolicyItemView,
    BulkReviewView,
    AutoAssignAuditsView,
    PolicyEventCreateView,
    RSSSourceCreateView,
    RSSSourceUpdateView,
    PolicyKeywordCreateView,
    PolicyKeywordUpdateView,
)

app_name = "policy"

# REST API Router
router = DefaultRouter()
router.register(r'rss/sources', RSSSourceConfigViewSet, basename='rss-source')
router.register(r'rss/logs', RSSFetchLogViewSet, basename='rss-log')
router.register(r'rss/keywords', PolicyLevelKeywordViewSet, basename='rss-keyword')

urlpatterns = [
    # 政策状态
    path("status/", PolicyStatusView.as_view(), name="status"),

    # 政策事件页面 (HTML)
    path("events/", PolicyEventsPageView.as_view(), name="events-page"),
    path("events/new/", PolicyEventCreateView.as_view(), name="event-create"),

    # 政策事件列表 (API) - new standard format (when mounted under /api/policy/)
    path("events/", PolicyEventListView.as_view(), name="event-list-api"),
    path("events/<str:event_date>/", PolicyEventDetailView.as_view(), name="event-detail-api"),

    # 政策事件列表 (API) - legacy format (backward compatibility)
    path("api/events/", PolicyEventListView.as_view(), name="event-list"),
    path("api/events/<str:event_date>/", PolicyEventDetailView.as_view(), name="event-detail-api-legacy"),

    # ========== 审核相关API ==========
    path("audit/queue/", AuditQueueView.as_view(), name="audit-queue"),
    path("audit/review/<int:policy_log_id>/", ReviewPolicyItemView.as_view(), name="review-policy"),
    path("audit/bulk_review/", BulkReviewView.as_view(), name="bulk-review"),
    path("audit/auto_assign/", AutoAssignAuditsView.as_view(), name="auto-assign"),

    # RSS 管理页面
    path("rss/manage/", RSSSourceListView.as_view(), name="rss-manage"),
    path("rss/manage/new/", RSSSourceCreateView.as_view(), name="rss-source-create"),
    path("rss/manage/<int:source_id>/edit/", RSSSourceUpdateView.as_view(), name="rss-source-edit"),
    path("rss/reader/", RSSReaderView.as_view(), name="rss-reader"),
    path("rss/keywords/", RSSKeywordListView.as_view(), name="rss-keywords"),
    path("rss/keywords/new/", PolicyKeywordCreateView.as_view(), name="rss-keyword-create"),
    path("rss/keywords/<int:keyword_id>/edit/", PolicyKeywordUpdateView.as_view(), name="rss-keyword-edit"),
    path("rss/logs/", RSSFetchLogListView.as_view(), name="rss-logs"),

    # RSS REST API - new standard format (when mounted under /api/policy/)
    path("", include(router.urls)),

    # RSS REST API - legacy format (backward compatibility)
    path("api/", include(router.urls)),
]
