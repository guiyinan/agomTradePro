"""Regime API URL configuration."""

from django.urls import include, path
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView

from .api_views import (
    RegimeActionView,
    RegimeHealthView,
    RegimeNavigatorHistoryView,
    RegimeNavigatorView,
    RegimeViewSet,
)

app_name = "regime_api"

router = DefaultRouter()
router.register(r"", RegimeViewSet, basename="regime")


class RegimeApiRootView(APIView):
    """Return discoverable regime API endpoints."""

    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "current": "/api/regime/current/",
                    "calculate": "/api/regime/calculate/",
                    "history": "/api/regime/history/",
                    "distribution": "/api/regime/distribution/",
                    "navigator": "/api/regime/navigator/",
                    "navigator_history": "/api/regime/navigator/history/",
                    "action": "/api/regime/action/",
                    "health": "/api/regime/health/",
                }
            }
        )

urlpatterns = [
    path("", RegimeApiRootView.as_view(), name="api-root"),
    path("", include(router.urls)),
    path("health/", RegimeHealthView.as_view(), name="health"),
    path("navigator/", RegimeNavigatorView.as_view(), name="regime-navigator"),
    path("action/", RegimeActionView.as_view(), name="regime-action"),
    path("navigator/history/", RegimeNavigatorHistoryView.as_view(), name="regime-navigator-history"),
]
