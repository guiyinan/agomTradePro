"""
Hedge Module API URL Configuration.

Provides API-only routes for /api/hedge/.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.http import JsonResponse

from apps.hedge.interface.views import (
    HedgePairViewSet,
    CorrelationHistoryViewSet,
    HedgePortfolioHoldingViewSet,
    HedgeAlertViewSet,
    HedgeActionViewSet,
)

app_name = "api_hedge"

router = DefaultRouter()
router.register(r"pairs", HedgePairViewSet, basename="hedge-pair")
router.register(r"correlations", CorrelationHistoryViewSet, basename="hedge-correlation")
router.register(r"holdings", HedgePortfolioHoldingViewSet, basename="hedge-holding")
router.register(r"alerts", HedgeAlertViewSet, basename="hedge-alert")
router.register(r"actions", HedgeActionViewSet, basename="hedge-action")


def api_home(request):
    return JsonResponse(
        {
            "message": "AgomSAAF Hedge Module API",
            "endpoints": {
                "pairs": "/api/hedge/pairs/",
                "correlations": "/api/hedge/correlations/",
                "holdings": "/api/hedge/holdings/",
                "alerts": "/api/hedge/alerts/",
                "actions": "/api/hedge/actions/",
            },
        }
    )


urlpatterns = [
    path("", api_home, name="home"),
    path("", include(router.urls)),
    path("health/", api_home, name="health"),
]
