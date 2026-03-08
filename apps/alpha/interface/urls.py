"""
Alpha URL Configuration

定义 Alpha 模块的 URL 路由。
"""

from django.http import JsonResponse
from django.urls import path

from . import views


app_name = "alpha"

urlpatterns = [
    # API 根路径（兼容旧调用）
    path("", lambda request: JsonResponse({
        "module": "alpha",
        "endpoints": [
            "/api/alpha/scores/",
            "/api/alpha/scores/upload/",
            "/api/alpha/stocks/",
            "/api/alpha/providers/status/",
            "/api/alpha/universes/",
            "/api/alpha/health/",
        ],
    }), name="api_root"),

    # 获取股票评分
    path("scores/", views.get_stock_scores, name="get_stock_scores"),

    # 上传本地 Qlib 推理结果（支持用户隔离）
    path("scores/upload/", views.upload_scores, name="upload_scores"),

    # 兼容旧路径
    path("stocks/", views.get_stock_scores, name="get_stock_scores_legacy"),

    # Provider 状态
    path("providers/status/", views.get_provider_status, name="provider_status"),

    # 支持的股票池
    path("universes/", views.get_available_universes, name="available_universes"),

    # 健康检查
    path("health/", views.health_check, name="health_check"),
]
