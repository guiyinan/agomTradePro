"""
Alpha Trigger URL Configuration

Alpha 事件触发的 URL 路由配置。
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from ..interface import views as alpha_trigger_views


# 创建路由器
router = DefaultRouter()
router.register(r"triggers", alpha_trigger_views.AlphaTriggerViewSet, basename="alpha-trigger")
router.register(r"candidates", alpha_trigger_views.AlphaCandidateViewSet, basename="alpha-candidate")

app_name = "alpha_trigger"

urlpatterns = [
    # ViewSet 路由
    path("api/alpha-triggers/", include(router.urls)),

    # 自定义操作路由
    path("api/alpha-triggers/create/", alpha_trigger_views.CreateTriggerView.as_view(), name="create-trigger"),
    path("api/alpha-triggers/check-invalidation/", alpha_trigger_views.CheckInvalidationView.as_view(), name="check-invalidation"),
    path("api/alpha-triggers/evaluate/", alpha_trigger_views.EvaluateTriggerView.as_view(), name="evaluate-trigger"),
    path("api/alpha-triggers/generate-candidate/", alpha_trigger_views.GenerateCandidateView.as_view(), name="generate-candidate"),
]
