"""
Beta Gate URL Configuration

硬闸门过滤的 URL 路由配置。

简化版本，只包含基本的 ViewSet 路由。
"""

from django.urls import path

from . import views as beta_gate_views

app_name = "beta_gate"

urlpatterns = [
    # Template 视图路由
    path("beta-gate/config/", beta_gate_views.beta_gate_config_view, name="config"),
    path("beta-gate/config/new/", beta_gate_views.beta_gate_config_create_view, name="config_new"),
    path("beta-gate/config/<str:config_id>/edit/", beta_gate_views.beta_gate_config_edit_view, name="config_edit"),
    path("beta-gate/config/<str:config_id>/activate/", beta_gate_views.beta_gate_config_activate_view, name="config_activate"),
    path("beta-gate/test/", beta_gate_views.beta_gate_test_view, name="test"),
    path("beta-gate/version/", beta_gate_views.beta_gate_version_view, name="version"),
]
