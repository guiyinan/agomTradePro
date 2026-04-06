"""
Sector API routes.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework.response import Response
from rest_framework.views import APIView

from .views import SectorDataUpdateView, SectorRotationViewSet

app_name = "sector"

router = DefaultRouter()
router.register(r"", SectorRotationViewSet, basename="sector")


class SectorApiRootView(APIView):
    """Return discoverable sector API endpoints."""

    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "rotation": "/api/sector/rotation/",
                    "analyze": "/api/sector/analyze/",
                    "update_data": "/api/sector/update-data/",
                }
            }
        )

urlpatterns = [
    path("", SectorApiRootView.as_view(), name="api-root"),
    path("", include(router.urls)),
    path("update-data/", SectorDataUpdateView.as_view(), name="sector-update-data"),
]
