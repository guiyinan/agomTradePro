"""AI provider API URL configuration."""

from django.urls import include, path
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView

from . import views

app_name = "ai_provider_api"

admin_router = DefaultRouter()
admin_router.register(r"providers", views.AIProviderConfigViewSet, basename="provider")
admin_router.register(r"logs", views.AIUsageLogViewSet, basename="log")
admin_router.register(r"admin/quotas", views.AdminUserFallbackQuotaViewSet, basename="admin-quota")

me_router = DefaultRouter()
me_router.register(r"me/providers", views.PersonalProviderViewSet, basename="my-provider")
me_router.register(r"me/logs", views.MyUsageLogViewSet, basename="my-log")
me_router.register(r"me/quota", views.UserFallbackQuotaViewSet, basename="my-quota")


class AIProviderApiRootView(APIView):
    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "providers": "/api/ai/providers/",
                    "logs": "/api/ai/logs/",
                    "me_providers": "/api/ai/me/providers/",
                    "me_logs": "/api/ai/me/logs/",
                    "me_quota": "/api/ai/me/quota/current/",
                    "admin_quotas": "/api/ai/admin/quotas/",
                }
            }
        )


urlpatterns = [
    path("", AIProviderApiRootView.as_view(), name="root"),
    path("", include(admin_router.urls)),
    path("", include(me_router.urls)),
]
