"""Pulse API URL configuration."""

from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_views import PulseCalculateView, PulseCurrentView, PulseHistoryView

app_name = "pulse_api"


class PulseApiRootView(APIView):
    """Return discoverable pulse API endpoints."""

    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "current": "/api/pulse/current/",
                    "history": "/api/pulse/history/",
                    "calculate": "/api/pulse/calculate/",
                }
            }
        )

urlpatterns = [
    path("", PulseApiRootView.as_view(), name="api-root"),
    path("current/", PulseCurrentView.as_view(), name="pulse-current"),
    path("history/", PulseHistoryView.as_view(), name="pulse-history"),
    path("calculate/", PulseCalculateView.as_view(), name="pulse-calculate"),
]
