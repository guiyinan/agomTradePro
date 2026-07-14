"""Realtime API URL configuration."""

from django.urls import path

from apps.realtime.interface.views import (
    HealthCheckView,
    MarketSummaryView,
    PricePollingTriggerView,
    RealtimePriceView,
    SectorPerformanceView,
    SingleAssetPriceView,
    TopMoversView,
)

app_name = "realtime"

urlpatterns = [
    path("prices/", RealtimePriceView.as_view(), name="price-list"),
    path("prices/<str:asset_code>/", SingleAssetPriceView.as_view(), name="price-detail"),
    path("sector-performance/", SectorPerformanceView.as_view(), name="sector-performance"),
    path("top-movers/", TopMoversView.as_view(), name="top-movers"),
    path("market-summary/", MarketSummaryView.as_view(), name="market-summary"),
    path("poll/", PricePollingTriggerView.as_view(), name="trigger-poll"),
    path("health/", HealthCheckView.as_view(), name="health-check"),
]
