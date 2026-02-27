"""
API URL configuration for policy module.

This file intentionally exposes API endpoints only.
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
    AuditQueueView,
    ReviewPolicyItemView,
    BulkReviewView,
    AutoAssignAuditsView,
    # 工作台视图
    WorkbenchSummaryView,
    WorkbenchItemsView,
    ApproveEventView,
    RejectEventView,
    RollbackEventView,
    OverrideEventView,
    SentimentGateStateView,
    IngestionConfigView,
    SentimentGateConfigView,
)

app_name = "policy"

router = DefaultRouter()
router.register(r"rss/sources", RSSSourceConfigViewSet, basename="rss-source")
router.register(r"rss/logs", RSSFetchLogViewSet, basename="rss-log")
router.register(r"rss/keywords", PolicyLevelKeywordViewSet, basename="rss-keyword")

urlpatterns = [
    path("status/", PolicyStatusView.as_view(), name="status"),
    path("events/", PolicyEventListView.as_view(), name="event-list"),
    path("events/<str:event_date>/", PolicyEventDetailView.as_view(), name="event-detail"),
    path("audit/queue/", AuditQueueView.as_view(), name="audit-queue"),
    path("audit/review/<int:policy_log_id>/", ReviewPolicyItemView.as_view(), name="review-policy"),
    path("audit/bulk_review/", BulkReviewView.as_view(), name="bulk-review"),
    path("audit/auto_assign/", AutoAssignAuditsView.as_view(), name="auto-assign"),
    # 工作台 API
    path("workbench/summary/", WorkbenchSummaryView.as_view(), name="workbench-summary"),
    path("workbench/items/", WorkbenchItemsView.as_view(), name="workbench-items"),
    path("workbench/items/<int:event_id>/approve/", ApproveEventView.as_view(), name="workbench-approve"),
    path("workbench/items/<int:event_id>/reject/", RejectEventView.as_view(), name="workbench-reject"),
    path("workbench/items/<int:event_id>/rollback/", RollbackEventView.as_view(), name="workbench-rollback"),
    path("workbench/items/<int:event_id>/override/", OverrideEventView.as_view(), name="workbench-override"),
    path("sentiment-gate/state/", SentimentGateStateView.as_view(), name="sentiment-gate-state"),
    path("ingestion-config/", IngestionConfigView.as_view(), name="ingestion-config"),
    path("sentiment-gate-config/", SentimentGateConfigView.as_view(), name="sentiment-gate-config"),
    path("", include(router.urls)),
    # Legacy under /api/policy/api/...
    path("api/", include(router.urls)),
]
