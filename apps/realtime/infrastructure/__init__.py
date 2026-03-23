"""
Realtime Module - URL Configuration

This module defines URL routing for the realtime price monitoring system.
"""

from django.urls import path

from apps.realtime.interface.views import (
    HealthCheckView,
    PricePollingTriggerView,
    RealtimePriceView,
    SingleAssetPriceView,
)

app_name = "realtime"

urlpatterns = [
    # 价格查询和轮询
    path("prices/", RealtimePriceView.as_view(), name="price-list"),
    path("prices/<str:asset_code>/", SingleAssetPriceView.as_view(), name="price-detail"),

    # 手动触发轮询
    path("poll/", PricePollingTriggerView.as_view(), name="trigger-poll"),

    # 健康检查
    path("health/", HealthCheckView.as_view(), name="health-check"),
]

