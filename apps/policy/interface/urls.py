"""
Interface Layer - URL Configuration for Policy Management

定义政策管理相关的 URL 路由。
"""

from django.urls import path, include
from django.views.generic import RedirectView
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
    # 工作台页面视图
    WorkbenchView,
)

app_name = "policy"

# REST API Router
router = DefaultRouter()
router.register(r'rss/sources', RSSSourceConfigViewSet, basename='rss-source')
router.register(r'rss/logs', RSSFetchLogViewSet, basename='rss-log')
router.register(r'rss/keywords', PolicyLevelKeywordViewSet, basename='rss-keyword')

urlpatterns = [
    # 工作台页面 (HTML)
    path("workbench/", WorkbenchView.as_view(), name="workbench"),

    # 政策状态
    path("status/", PolicyStatusView.as_view(), name="status"),

    # ========== 301 重定向旧页面到工作台 ==========
    path("events/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="events-page"),
    path("events/new/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="event-create"),
    path("events/<str:event_date>/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="events-page-detail"),
    path("audit/queue/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="audit-queue"),
    path("rss/manage/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="rss-manage"),
    path("rss/manage/new/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="rss-source-create"),
    path("rss/manage/<int:source_id>/edit/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="rss-source-edit"),
    path("rss/reader/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="rss-reader"),
    path("rss/keywords/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="rss-keywords"),
    path("rss/keywords/new/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="rss-keyword-create"),
    path("rss/keywords/<int:keyword_id>/edit/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="rss-keyword-edit"),
    path("rss/logs/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="rss-logs"),

    # 政策事件列表 (API) - legacy format (backward compatibility)
    path("api/events/", PolicyEventListView.as_view(), name="event-list"),
    path("api/events/<str:event_date>/", PolicyEventDetailView.as_view(), name="event-detail-api-legacy"),

    # ========== 审核相关API ==========
    path("audit/review/<int:policy_log_id>/", ReviewPolicyItemView.as_view(), name="review-policy"),
    path("audit/bulk_review/", BulkReviewView.as_view(), name="bulk-review"),
    path("audit/auto_assign/", AutoAssignAuditsView.as_view(), name="auto-assign"),

    # RSS REST API - new standard format (when mounted under /api/policy/)
    path("", include(router.urls)),

    # RSS REST API - legacy format (backward compatibility)
    path("api/", include(router.urls)),
]
