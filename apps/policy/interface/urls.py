"""
Interface Layer - URL Configuration for Policy Management

定义政策管理相关的 URL 路由。
"""

from django.urls import path, include
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter
from .views import (
    PolicyStatusView,
    RSSSourceConfigViewSet,
    RSSFetchLogViewSet,
    PolicyLevelKeywordViewSet,
    ReviewPolicyItemView,
    BulkReviewView,
    AutoAssignAuditsView,
    PolicyEventsPageView,
    PolicyEventCreateView,
    RSSSourceListView,
    RSSSourceCreateView,
    RSSSourceUpdateView,
    RSSReaderView,
    RSSKeywordListView,
    PolicyKeywordCreateView,
    PolicyKeywordUpdateView,
    RSSFetchLogListView,
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
    path("manage/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="manage-redirect"),

    # 政策状态
    path("status/", PolicyStatusView.as_view(), name="status"),

    # ========== 页面路由 ==========
    path("events/", PolicyEventsPageView.as_view(), name="events-page"),
    path("events/new/", PolicyEventCreateView.as_view(), name="event-create"),
    path("events/<str:event_date>/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="events-page-detail"),
    path("audit/queue/", RedirectView.as_view(url='/policy/workbench/', permanent=True), name="audit-queue"),
    # RSS 页面（新主路径，避免历史 301 缓存污染）
    path("rss/sources/", RSSSourceListView.as_view(), name="rss-manage"),
    path("rss/sources/new/", RSSSourceCreateView.as_view(), name="rss-source-create"),
    path("rss/sources/<int:source_id>/edit/", RSSSourceUpdateView.as_view(), name="rss-source-edit"),
    path("rss/reader/", RSSReaderView.as_view(), name="rss-reader"),
    path("rss/keywords/", RSSKeywordListView.as_view(), name="rss-keywords"),
    path("rss/keywords/new/", PolicyKeywordCreateView.as_view(), name="rss-keyword-create"),
    path("rss/keywords/<int:keyword_id>/edit/", PolicyKeywordUpdateView.as_view(), name="rss-keyword-edit"),
    path("rss/logs/", RSSFetchLogListView.as_view(), name="rss-logs"),

    # RSS 旧路径兼容（临时跳转，不使用 permanent 避免缓存）
    path("rss/manage/", RedirectView.as_view(url='/policy/rss/sources/', permanent=False), name="rss-manage-legacy"),
    path("rss/manage/new/", RedirectView.as_view(url='/policy/rss/sources/new/', permanent=False), name="rss-source-create-legacy"),
    path("rss/manage/<int:source_id>/edit/", RedirectView.as_view(url='/policy/rss/sources/%(source_id)s/edit/', permanent=False), name="rss-source-edit-legacy"),

    # ========== 审核相关API ==========
    path("audit/review/<int:policy_log_id>/", ReviewPolicyItemView.as_view(), name="review-policy"),
    path("audit/bulk_review/", BulkReviewView.as_view(), name="bulk-review"),
    path("audit/auto_assign/", AutoAssignAuditsView.as_view(), name="auto-assign"),

    # Note: API routes are now handled by api_urls.py mounted at /api/policy/
    # The router is defined here for reference but not included to avoid duplication
]
