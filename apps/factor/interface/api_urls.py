"""
Factor Module API URL Configuration.

Provides API-only routes for /api/factor/.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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


class FactorApiHomeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
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
    path("", FactorApiHomeView.as_view(), name="home"),
    path("", include(router.urls)),
    path("health/", FactorApiHomeView.as_view(), name="health"),
]
