"""
资产分析模块 - URL 路由配置
"""

from django.urls import path
from apps.asset_analysis.interface.views import (
    MultiDimScreenAPIView,
    WeightConfigsAPIView,
    CurrentWeightAPIView,
)

app_name = "asset_analysis"

urlpatterns = [
    # 多维度筛选 API
    path("multidim-screen/", MultiDimScreenAPIView.as_view(), name="multidim_screen"),

    # 权重配置 API
    path("weight-configs/", WeightConfigsAPIView.as_view(), name="weight_configs"),
    path("current-weight/", CurrentWeightAPIView.as_view(), name="current_weight"),
]
