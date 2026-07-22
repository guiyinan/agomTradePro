from django.urls import path

from .api_views import (
    TransitionPlanApproveView,
    TransitionPlanDetailView,
    TransitionPlanListCreateView,
    TransitionPlanSubmitView,
)

app_name = "portfolio"

urlpatterns = [
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

