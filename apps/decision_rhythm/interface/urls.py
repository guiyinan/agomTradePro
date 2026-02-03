"""
Decision Rhythm URL Configuration

决策频率约束和配额管理的 URL 路由配置。
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views as decision_rhythm_views


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
]
