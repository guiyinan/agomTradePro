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

    # 政策事件列表
    path("events/", PolicyEventListView.as_view(), name="event-list"),

    # 政策事件详情
    path("events/<str:event_date>/", PolicyEventDetailView.as_view(), name="event-detail"),

    # ========== 审核相关API ==========
    path("audit/queue/", AuditQueueView.as_view(), name="audit-queue"),
    path("audit/review/<int:policy_log_id>/", ReviewPolicyItemView.as_view(), name="review-policy"),
    path("audit/bulk_review/", BulkReviewView.as_view(), name="bulk-review"),
    path("audit/auto_assign/", AutoAssignAuditsView.as_view(), name="auto-assign"),

    # RSS 管理页面
    path("rss/manage/", RSSSourceListView.as_view(), name="rss-manage"),
    path("rss/reader/", RSSReaderView.as_view(), name="rss-reader"),
    path("rss/keywords/", RSSKeywordListView.as_view(), name="rss-keywords"),
    path("rss/logs/", RSSFetchLogListView.as_view(), name="rss-logs"),

    # RSS REST API
    path("api/", include(router.urls)),
]
