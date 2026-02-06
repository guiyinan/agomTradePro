"""
Alpha URL Configuration

定义 Alpha 模块的 URL 路由。
"""

from django.urls import path

from . import views


app_name = "alpha"

urlpatterns = [
    # 获取股票评分
    path("scores/", views.get_stock_scores, name="get_stock_scores"),

    # Provider 状态
    path("providers/status/", views.get_provider_status, name="provider_status"),

    # 支持的股票池
    path("universes/", views.get_available_universes, name="available_universes"),

    # 健康检查
    path("health/", views.health_check, name="health_check"),
]
