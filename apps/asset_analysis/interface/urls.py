"""
资产分析模块 - URL 路由配置
"""

from django.http import JsonResponse
from django.urls import path
from apps.asset_analysis.interface.views import (
    MultiDimScreenAPIView,
    WeightConfigsAPIView,
    CurrentWeightAPIView,
)
from apps.asset_analysis.interface.pool_views import (
    AssetPoolScreenAPIView,
    AssetPoolSummaryAPIView,
)

app_name = "asset_analysis"

urlpatterns = [
    # API 根路径（兼容旧调用）
    path("", lambda request: JsonResponse({
        "module": "asset-analysis",
        "endpoints": [
            "/api/asset-analysis/multidim-screen/",
            "/api/asset-analysis/weight-configs/",
            "/api/asset-analysis/current-weight/",
            "/api/asset-analysis/pool-summary/",
        ],
    }), name="api_root"),

    # 多维度筛选 API
    path("multidim-screen/", MultiDimScreenAPIView.as_view(), name="multidim_screen"),

    # 权重配置 API
    path("weight-configs/", WeightConfigsAPIView.as_view(), name="weight_configs"),
    path("current-weight/", CurrentWeightAPIView.as_view(), name="current_weight"),

    # 资产池 API
    path("screen/<str:asset_type>/", AssetPoolScreenAPIView.as_view(), name="pool_screen"),
    path("pool-summary/", AssetPoolSummaryAPIView.as_view(), name="pool_summary"),
]
