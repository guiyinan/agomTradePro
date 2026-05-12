"""Decision rhythm API URL configuration."""

from django.urls import include, path
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView

from .command_api_views import (
    GetRhythmSummaryView,
    SubmitBatchRequestView,
    SubmitDecisionRequestView,
)
from .cooldown_api_views import CooldownPeriodViewSet
from .quota_api_views import DecisionQuotaViewSet, ResetQuotaView, TrendDataView
from .recommendation_api_views import (
    ConflictsView,
    ModelParamsView,
    RecommendationUserActionView,
    RefreshRecommendationsView,
    UnifiedRecommendationsView,
    UpdateModelParamView,
)
from .request_api_views import DecisionRequestViewSet
from .valuation_api_views import (
    InvalidationAIDraftView,
    InvalidationTemplateView,
    ValuationRecalculateView,
    ValuationSnapshotDetailView,
)
from .workflow_api_views import (
    CancelDecisionRequestView,
    ExecuteDecisionRequestView,
    PrecheckDecisionView,
    UpdateQuotaConfigView,
)
from .workspace_execution_api_views import (
    AggregatedWorkspaceView,
    ExecutionApproveView,
    ExecutionPreviewView,
    ExecutionRejectView,
    ExecutionRequestDetailView,
    TransitionPlanDetailView,
    TransitionPlanGenerateView,
    TransitionPlanUpdateView,
)

router = DefaultRouter()
router.register(r"quotas", DecisionQuotaViewSet, basename="decision-quota")
router.register(r"cooldowns", CooldownPeriodViewSet, basename="cooldown-period")
router.register(r"requests", DecisionRequestViewSet, basename="decision-request")


class DecisionApiRootView(APIView):
    """Return discoverable decision workflow API endpoints."""

    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "workspace_recommendations": "/api/decision/workspace/recommendations/",
                    "workspace_conflicts": "/api/decision/workspace/conflicts/",
                    "workspace_params": "/api/decision/workspace/params/",
                    "workspace_plans_generate": "/api/decision/workspace/plans/generate/",
                    "execute_preview": "/api/decision/execute/preview/",
                    "execute_approve": "/api/decision/execute/approve/",
                    "execute_reject": "/api/decision/execute/reject/",
                    "funnel_context": "/api/decision/funnel/context/",
                    "audit": "/api/decision/audit/",
                }
            }
        )

urlpatterns = [
    path("api/decision/", DecisionApiRootView.as_view(), name="decision-api-root"),
    path("api/decision-rhythm/", include(router.urls)),
    path("api/decision-rhythm/submit/", SubmitDecisionRequestView.as_view(), name="submit-request"),
    path(
        "api/decision-rhythm/submit-batch/", SubmitBatchRequestView.as_view(), name="submit-batch"
    ),
    path("api/decision-rhythm/summary/", GetRhythmSummaryView.as_view(), name="rhythm-summary"),
    path("api/decision-rhythm/reset-quota/", ResetQuotaView.as_view(), name="reset-quota"),
    path("api/decision-rhythm/trend-data/", TrendDataView.as_view(), name="api_trend_data"),
    path("api/decision-workflow/precheck/", PrecheckDecisionView.as_view(), name="precheck"),
    path(
        "api/decision-rhythm/requests/<str:request_id>/execute/",
        ExecuteDecisionRequestView.as_view(),
        name="execute-request",
    ),
    path(
        "api/decision-rhythm/requests/<str:request_id>/cancel/",
        CancelDecisionRequestView.as_view(),
        name="cancel-request",
    ),
    path(
        "api/decision-rhythm/quota/update/",
        UpdateQuotaConfigView.as_view(),
        name="api_update_quota",
    ),
    path(
        "api/valuation/snapshot/<str:snapshot_id>/",
        ValuationSnapshotDetailView.as_view(),
        name="valuation-snapshot-detail",
    ),
    path(
        "api/valuation/recalculate/",
        ValuationRecalculateView.as_view(),
        name="valuation-recalculate",
    ),
    path(
        "api/decision/workspace/aggregated/",
        AggregatedWorkspaceView.as_view(),
        name="decision-workspace-aggregated",
    ),
    path(
        "api/decision/workspace/plans/generate/",
        TransitionPlanGenerateView.as_view(),
        name="decision-workspace-plan-generate",
    ),
    path(
        "api/decision/workspace/plans/<str:plan_id>/",
        TransitionPlanDetailView.as_view(),
        name="decision-workspace-plan-detail",
    ),
    path(
        "api/decision/workspace/plans/<str:plan_id>/update/",
        TransitionPlanUpdateView.as_view(),
        name="decision-workspace-plan-update",
    ),
    path(
        "api/decision/workspace/invalidation/template/",
        InvalidationTemplateView.as_view(),
        name="decision-workspace-invalidation-template",
    ),
    path(
        "api/decision/workspace/invalidation/ai-draft/",
        InvalidationAIDraftView.as_view(),
        name="decision-workspace-invalidation-ai-draft",
    ),
    path(
        "api/decision/execute/preview/",
        ExecutionPreviewView.as_view(),
        name="decision-execute-preview",
    ),
    path(
        "api/decision/execute/approve/",
        ExecutionApproveView.as_view(),
        name="decision-execute-approve",
    ),
    path(
        "api/decision/execute/reject/",
        ExecutionRejectView.as_view(),
        name="decision-execute-reject",
    ),
    path(
        "api/decision/execute/<str:request_id>/",
        ExecutionRequestDetailView.as_view(),
        name="decision-execute-detail",
    ),
    path(
        "api/decision/workspace/recommendations/",
        UnifiedRecommendationsView.as_view(),
        name="unified-recommendations",
    ),
    path(
        "api/decision/workspace/recommendations/action/",
        RecommendationUserActionView.as_view(),
        name="recommendation-user-action",
    ),
    path(
        "api/decision/workspace/recommendations/refresh/",
        RefreshRecommendationsView.as_view(),
        name="refresh-recommendations",
    ),
    path(
        "api/decision/workspace/conflicts/",
        ConflictsView.as_view(),
        name="recommendation-conflicts",
    ),
    path("api/decision/workspace/params/", ModelParamsView.as_view(), name="model-params"),
    path(
        "api/decision/workspace/params/update/",
        UpdateModelParamView.as_view(),
        name="update-model-param",
    ),
]
