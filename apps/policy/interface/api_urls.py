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
    path("", include(router.urls)),
    # Legacy under /api/policy/api/...
    path("api/", include(router.urls)),
]
