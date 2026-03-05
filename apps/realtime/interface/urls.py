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
    # Page redirect (legacy support)
    path("", RedirectView.as_view(url="/api/realtime/prices/", permanent=False), name="home"),

    # API routes - new standard format (when mounted under /api/realtime/)
    path("prices/", RealtimePriceView.as_view(), name="price-list"),
    path("prices/<str:asset_code>/", SingleAssetPriceView.as_view(), name="price-detail"),
    path("poll/", PricePollingTriggerView.as_view(), name="trigger-poll"),
    path("health/", HealthCheckView.as_view(), name="health-check"),
]
