"""
Beta Gate URL Configuration

硬闸门过滤的 URL 路由配置。

简化版本，只包含基本的 ViewSet 路由。
"""

from django.urls import include, path
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
    # API 端点
    path("api/beta-gate/test/", beta_gate_views.BetaGateTestAPIView.as_view(), name="api_test"),
    path("api/beta-gate/version/compare/", beta_gate_views.BetaGateVersionCompareAPIView.as_view(), name="api_version_compare"),
    path("api/beta-gate/config/rollback/<str:config_id>/", beta_gate_views.RollbackConfigView.as_view(), name="api_rollback"),
    path("api/beta-gate/config/suggest/", beta_gate_views.BetaGateJsonSuggestAPIView.as_view(), name="api_config_suggest"),
    # Template 视图路由
    path("beta-gate/config/", beta_gate_views.beta_gate_config_view, name="config"),
    path("beta-gate/config/new/", beta_gate_views.beta_gate_config_create_view, name="config_new"),
    path("beta-gate/config/<str:config_id>/edit/", beta_gate_views.beta_gate_config_edit_view, name="config_edit"),
    path("beta-gate/config/<str:config_id>/activate/", beta_gate_views.beta_gate_config_activate_view, name="config_activate"),
    path("beta-gate/test/", beta_gate_views.beta_gate_test_view, name="test"),
    path("beta-gate/version/", beta_gate_views.beta_gate_version_view, name="version"),
]
