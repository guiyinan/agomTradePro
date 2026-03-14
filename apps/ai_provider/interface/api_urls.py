"""AI provider API URL configuration."""

from django.urls import include, path
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView

from . import views

app_name = "ai_provider_api"

router = DefaultRouter()
router.register(r"providers", views.AIProviderConfigViewSet, basename="provider")
router.register(r"logs", views.AIUsageLogViewSet, basename="log")


class AIProviderApiRootView(APIView):
    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "providers": "/api/ai/providers/",
                    "logs": "/api/ai/logs/",
                }
            }
        )


urlpatterns = [
    path("", AIProviderApiRootView.as_view(), name="api-root"),
    path("", include(router.urls)),
]
