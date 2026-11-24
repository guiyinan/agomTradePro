from django.urls import include, path

from .api_views import (
    TransitionPlanApproveView,
    TransitionPlanDetailView,
    TransitionPlanListCreateView,
    TransitionPlanSubmitView,
)
from .benchmark_approval_views import BenchmarkApprovalCommandView, BenchmarkApprovalReviewView

app_name = "portfolio"

urlpatterns = [
    path("benchmark-valuations/", include("apps.portfolio.interface.benchmark_valuation_urls")),
    path(
        "benchmark-approvals/<uuid:request_id>/",
        BenchmarkApprovalReviewView.as_view(),
        name="benchmark-review",
    ),
    path("benchmark-approvals/", BenchmarkApprovalCommandView.as_view(), name="benchmark-submit"),
    path(
        "benchmark-approvals/<uuid:request_id>/approve/",
        BenchmarkApprovalCommandView.as_view(action="approve"),
        name="benchmark-approve",
    ),
    path(
        "benchmark-approvals/<uuid:request_id>/revoke/",
        BenchmarkApprovalCommandView.as_view(action="revoke"),
        name="benchmark-revoke",
    ),
    path("transition-plans/", TransitionPlanListCreateView.as_view(), name="plan-list"),
    path("transition-plans/<str:plan_id>/", TransitionPlanDetailView.as_view(), name="plan-detail"),
    path(
        "transition-plans/<str:plan_id>/approve/",
        TransitionPlanApproveView.as_view(),
        name="plan-approve",
    ),
    path(
        "transition-plans/<str:plan_id>/submit/",
        TransitionPlanSubmitView.as_view(),
        name="plan-submit",
    ),
]
