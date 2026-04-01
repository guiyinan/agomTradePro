"""
Asset analysis API routes.

API 路由只挂在 /api/asset-analysis/*。
"""

from django.http import JsonResponse
from django.urls import path

from apps.asset_analysis.interface.pool_views import (
    AssetPoolScreenAPIView,
    AssetPoolSummaryAPIView,
)
from apps.asset_analysis.interface.views import (
    CurrentWeightAPIView,
    MultiDimScreenAPIView,
    WeightConfigsAPIView,
)

app_name = "asset_analysis"

urlpatterns = [
    path(
        "",
        lambda request: JsonResponse(
            {
                "module": "asset-analysis",
                "endpoints": [
                    "/api/asset-analysis/multidim-screen/",
                    "/api/asset-analysis/weight-configs/",
                    "/api/asset-analysis/current-weight/",
                    "/api/asset-analysis/screen/{asset_type}/",
                    "/api/asset-analysis/pool-summary/",
                ],
            }
        ),
        name="root",
    ),
    path("multidim-screen/", MultiDimScreenAPIView.as_view(), name="multidim_screen"),
    path("weight-configs/", WeightConfigsAPIView.as_view(), name="weight_configs"),
    path("current-weight/", CurrentWeightAPIView.as_view(), name="current_weight"),
    path("screen/<str:asset_type>/", AssetPoolScreenAPIView.as_view(), name="pool_screen"),
    path("pool-summary/", AssetPoolSummaryAPIView.as_view(), name="pool_summary"),
]
