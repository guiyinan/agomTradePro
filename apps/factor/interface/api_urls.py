"""
Factor Module API URL Configuration.

Provides API-only routes for /api/factor/.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.http import JsonResponse

from apps.factor.interface.views import (
    FactorDefinitionViewSet,
    FactorPortfolioConfigViewSet,
    FactorActionViewSet,
)

app_name = "api_factor"

router = DefaultRouter()
router.register(r"definitions", FactorDefinitionViewSet, basename="factor-definition")
router.register(r"configs", FactorPortfolioConfigViewSet, basename="factor-config")
router.register(r"", FactorActionViewSet, basename="factor-action")


def api_home(request):
    return JsonResponse(
        {
            "message": "AgomSAAF Factor Module API",
            "endpoints": {
                "definitions": "/api/factor/definitions/",
                "configs": "/api/factor/configs/",
                "actions": "/api/factor/",
            },
        }
    )


urlpatterns = [
    path("", api_home, name="home"),
    path("", include(router.urls)),
    path("health/", api_home, name="health"),
]
