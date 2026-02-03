"""
Beta Gate URL Configuration

硬闸门过滤的 URL 路由配置。

简化版本，只包含基本的 ViewSet 路由。
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views as beta_gate_views


# 创建路由器
router = DefaultRouter()
router.register(r"configs", beta_gate_views.GateConfigViewSet, basename="gate-config")
router.register(r"decisions", beta_gate_views.GateDecisionViewSet, basename="gate-decision")
router.register(r"universe", beta_gate_views.VisibilityUniverseViewSet, basename="visibility-universe")

app_name = "beta_gate"

urlpatterns = [
    # ViewSet 路由
    path("api/beta-gate/", include(router.urls)),
]
