from django.http import JsonResponse
from django.urls import path

from apps.realtime.interface.views import (
    HealthCheckView,
    MarketSummaryView,
    PricePollingTriggerView,
    RealtimePriceView,
    SingleAssetPriceView,
)

app_name = "realtime"

urlpatterns = [
    path(
        "",
        lambda request: JsonResponse(
            {
                "module": "realtime",
                "endpoints": [
                    "/api/realtime/prices/",
                    "/api/realtime/market-summary/",
                    "/api/realtime/poll/",
                    "/api/realtime/health/",
                ],
            }
        ),
        name="home",
    ),

    # API routes - new standard format (when mounted under /api/realtime/)
    path("prices/", RealtimePriceView.as_view(), name="price-list"),
    path("prices/<str:asset_code>/", SingleAssetPriceView.as_view(), name="price-detail"),
    path("market-summary/", MarketSummaryView.as_view(), name="market-summary"),
    path("poll/", PricePollingTriggerView.as_view(), name="trigger-poll"),
    path("health/", HealthCheckView.as_view(), name="health-check"),
]
