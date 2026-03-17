"""Prompt API URL configuration."""

from django.urls import include, path
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView

from .views import (
    ChainConfigViewSet,
    ChatModelsView,
    ChatProvidersView,
    ChatView,
    ExecutionLogViewSet,
    PromptTemplateViewSet,
    ReportGenerationView,
    SignalGenerationView,
)

app_name = "prompt_api"

router = DefaultRouter()
router.register(r"templates", PromptTemplateViewSet, basename="prompt-template")
router.register(r"chains", ChainConfigViewSet, basename="chain-config")
router.register(r"logs", ExecutionLogViewSet, basename="execution-log")


class PromptApiRootView(APIView):
    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "templates": "/api/prompt/templates/",
                    "chains": "/api/prompt/chains/",
                    "logs": "/api/prompt/logs/",
                    "reports_generate": "/api/prompt/reports/generate",
                    "signals_generate": "/api/prompt/signals/generate",
                    "chat": "/api/prompt/chat",
                    "chat_providers": "/api/prompt/chat/providers",
                    "chat_models": "/api/prompt/chat/models",
                }
            }
        )


urlpatterns = [
    path("", PromptApiRootView.as_view(), name="api-root"),
    path("", include(router.urls)),
    path("reports/generate", ReportGenerationView.as_view(), name="generate-report"),
    path("signals/generate", SignalGenerationView.as_view(), name="generate-signal"),
    path("chat", ChatView.as_view(), name="chat"),
    path("chat/providers", ChatProvidersView.as_view(), name="chat-providers"),
    path("chat/models", ChatModelsView.as_view(), name="chat-models"),
]