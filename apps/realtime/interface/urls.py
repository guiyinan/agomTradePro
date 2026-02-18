"""
Realtime Module - URL Configuration

This module defines URL routing for the realtime price monitoring system.
"""

from django.urls import path
from django.views.generic import RedirectView

from apps.realtime.interface.views import (
    RealtimePriceView,
    SingleAssetPriceView,
    PricePollingTriggerView,
    HealthCheckView
)

app_name = "realtime"

urlpatterns = [
    # 向后兼容重定向 (旧路由重定向到新路由)
    path("prices/", RedirectView.as_view(url="/realtime/api/prices/", permanent=False)),
    path("prices/<str:asset_code>/", RedirectView.as_view(url="/realtime/api/prices/%(asset_code)s/", permanent=False)),
    path("poll/", RedirectView.as_view(url="/realtime/api/poll/", permanent=False)),
    path("health/", RedirectView.as_view(url="/realtime/api/health/", permanent=False)),

    # API 路由 - 价格查询和轮询
    path("api/prices/", RealtimePriceView.as_view(), name="price-list"),
    path("api/prices/<str:asset_code>/", SingleAssetPriceView.as_view(), name="price-detail"),

    # API 路由 - 手动触发轮询
    path("api/poll/", PricePollingTriggerView.as_view(), name="trigger-poll"),

    # API 路由 - 健康检查
    path("api/health/", HealthCheckView.as_view(), name="health-check"),
]
