"""Realtime API URL configuration."""

from django.urls import path

from apps.realtime.interface.views import (
    HealthCheckView,
    MarketSummaryView,
    PriceAlertDetailView,
    PriceAlertListCreateView,
    PricePollingTriggerView,
    PriceSubscriptionDetailView,
    PriceSubscriptionListCreateView,
    RealtimeApiRootView,
    RealtimePriceView,
    SectorPerformanceView,
    SingleAssetPriceView,
    TopMoversView,
)

app_name = "realtime"

urlpatterns = [
    path("", RealtimeApiRootView.as_view(), name="api-root"),
    path("alerts/", PriceAlertListCreateView.as_view(), name="alert-list"),
    path("alerts/<int:alert_id>/", PriceAlertDetailView.as_view(), name="alert-detail"),
    path(
        "subscriptions/",
        PriceSubscriptionListCreateView.as_view(),
        name="subscription-list",
    ),
    path(
        "subscriptions/<str:asset_code>/",
        PriceSubscriptionDetailView.as_view(),
        name="subscription-detail",
    ),
    path("prices/", RealtimePriceView.as_view(), name="price-list"),
    path("prices/<str:asset_code>/", SingleAssetPriceView.as_view(), name="price-detail"),
    path("sector-performance/", SectorPerformanceView.as_view(), name="sector-performance"),
    path("top-movers/", TopMoversView.as_view(), name="top-movers"),
    path("market-summary/", MarketSummaryView.as_view(), name="market-summary"),
    path("poll/", PricePollingTriggerView.as_view(), name="trigger-poll"),
    path("health/", HealthCheckView.as_view(), name="health-check"),
]
