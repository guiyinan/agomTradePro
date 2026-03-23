"""
Decision Rhythm URL Configuration

决策频率约束和配额管理的 URL 路由配置。
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views as decision_rhythm_views
from . import api_views as decision_rhythm_api_views


# 创建路由器
router = DefaultRouter()
router.register(r"quotas", decision_rhythm_views.DecisionQuotaViewSet, basename="decision-quota")
router.register(r"cooldowns", decision_rhythm_views.CooldownPeriodViewSet, basename="cooldown-period")
router.register(r"requests", decision_rhythm_views.DecisionRequestViewSet, basename="decision-request")

app_name = "decision_rhythm"

urlpatterns = [
    # ViewSet 路由
    path("api/decision-rhythm/", include(router.urls)),

    # 自定义操作路由
    path("api/decision-rhythm/submit/", decision_rhythm_views.SubmitDecisionRequestView.as_view(), name="submit-request"),
    path("api/decision-rhythm/submit-batch/", decision_rhythm_views.SubmitBatchRequestView.as_view(), name="submit-batch"),
    path("api/decision-rhythm/summary/", decision_rhythm_views.GetRhythmSummaryView.as_view(), name="rhythm-summary"),
    path("api/decision-rhythm/reset-quota/", decision_rhythm_views.ResetQuotaView.as_view(), name="reset-quota"),
    path("api/decision-rhythm/trend-data/", decision_rhythm_views.TrendDataView.as_view(), name="api_trend_data"),

    # 决策执行相关 API（WP-2 新增）
    path("api/decision-workflow/precheck/", decision_rhythm_views.PrecheckDecisionView.as_view(), name="precheck"),
    path("api/decision-rhythm/requests/<str:request_id>/execute/", decision_rhythm_views.ExecuteDecisionRequestView.as_view(), name="execute-request"),
    path("api/decision-rhythm/requests/<str:request_id>/cancel/", decision_rhythm_views.CancelDecisionRequestView.as_view(), name="cancel-request"),

    # Template 视图路由
    path("decision-rhythm/quota/", decision_rhythm_views.decision_rhythm_quota_view, name="quota"),
    path("decision-rhythm/config/", decision_rhythm_views.decision_rhythm_config_view, name="config"),

    # API 端点
    path("api/decision-rhythm/quota/update/", decision_rhythm_views.UpdateQuotaConfigView.as_view(), name="api_update_quota"),

    # 估值与执行审批 API（外包闭环）
    path("api/valuation/snapshot/<str:snapshot_id>/", decision_rhythm_api_views.ValuationSnapshotDetailView.as_view(), name="valuation-snapshot-detail"),
    path("api/valuation/recalculate/", decision_rhythm_api_views.ValuationRecalculateView.as_view(), name="valuation-recalculate"),
    path("api/decision/workspace/aggregated/", decision_rhythm_api_views.AggregatedWorkspaceView.as_view(), name="decision-workspace-aggregated"),
    path("api/decision/execute/preview/", decision_rhythm_api_views.ExecutionPreviewView.as_view(), name="decision-execute-preview"),
    path("api/decision/execute/approve/", decision_rhythm_api_views.ExecutionApproveView.as_view(), name="decision-execute-approve"),
    path("api/decision/execute/reject/", decision_rhythm_api_views.ExecutionRejectView.as_view(), name="decision-execute-reject"),
    path("api/decision/execute/<str:request_id>/", decision_rhythm_api_views.ExecutionRequestDetailView.as_view(), name="decision-execute-detail"),

    # 统一推荐 API（Top-down + Bottom-up 融合）
    path("api/decision/workspace/recommendations/", decision_rhythm_api_views.UnifiedRecommendationsView.as_view(), name="unified-recommendations"),
    path("api/decision/workspace/recommendations/action/", decision_rhythm_api_views.RecommendationUserActionView.as_view(), name="recommendation-user-action"),
    path("api/decision/workspace/recommendations/refresh/", decision_rhythm_api_views.RefreshRecommendationsView.as_view(), name="refresh-recommendations"),
    path("api/decision/workspace/conflicts/", decision_rhythm_api_views.ConflictsView.as_view(), name="recommendation-conflicts"),
    path("api/decision/workspace/params/", decision_rhythm_api_views.ModelParamsView.as_view(), name="model-params"),
    path("api/decision/workspace/params/update/", decision_rhythm_api_views.UpdateModelParamView.as_view(), name="update-model-param"),
]
