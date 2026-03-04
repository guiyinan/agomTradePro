"""
Rotation Module API URL Configuration.

Provides API-only routes for /api/rotation/.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.http import JsonResponse

from apps.rotation.interface.views import (
    AssetClassViewSet,
    RotationConfigViewSet,
    RotationSignalViewSet,
    RotationActionViewSet,
)

app_name = "api_rotation"

router = DefaultRouter()
router.register(r"assets", AssetClassViewSet, basename="rotation-asset")
router.register(r"configs", RotationConfigViewSet, basename="rotation-config")
router.register(r"signals", RotationSignalViewSet, basename="rotation-signal")
router.register(r"", RotationActionViewSet, basename="rotation-action")


def api_home(request):
    return JsonResponse(
        {
            "message": "AgomSAAF Rotation Module API",
            "endpoints": {
                "assets": "/api/rotation/assets/",
                "configs": "/api/rotation/configs/",
                "signals": "/api/rotation/signals/",
                "actions": "/api/rotation/",
            },
        }
    )


urlpatterns = [
    path("", api_home, name="home"),
    path("", include(router.urls)),
    path("health/", api_home, name="health"),
]
