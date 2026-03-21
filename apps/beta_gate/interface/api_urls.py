"""
Beta Gate API URL Configuration.

Provides API-only routes for /api/beta-gate/.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.beta_gate.interface import views as beta_gate_views

app_name = "api_beta_gate"

router = DefaultRouter()
router.register(r"configs", beta_gate_views.GateConfigViewSet, basename="gate-config")
router.register(r"decisions", beta_gate_views.GateDecisionViewSet, basename="gate-decision")
router.register(r"universe", beta_gate_views.VisibilityUniverseViewSet, basename="visibility-universe")


class BetaGateApiHomeView(APIView):
    def get(self, request):
        return Response(
            {
                "message": "AgomTradePro Beta Gate API",
                "endpoints": {
                    "configs": "/api/beta-gate/configs/",
                    "decisions": "/api/beta-gate/decisions/",
                    "universe": "/api/beta-gate/universe/",
                    "test": "/api/beta-gate/test/",
                },
            }
        )


urlpatterns = [
    path("", BetaGateApiHomeView.as_view(), name="home"),
    path("", include(router.urls)),
    path("health/", BetaGateApiHomeView.as_view(), name="health"),
    path("test/", beta_gate_views.BetaGateTestAPIView.as_view(), name="test"),
    path("version/compare/", beta_gate_views.BetaGateVersionCompareAPIView.as_view(), name="version-compare"),
    path("config/rollback/<str:config_id>/", beta_gate_views.RollbackConfigView.as_view(), name="rollback"),
    path("config/suggest/", beta_gate_views.BetaGateJsonSuggestAPIView.as_view(), name="config-suggest"),
]
