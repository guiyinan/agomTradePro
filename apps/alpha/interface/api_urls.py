"""Alpha API URL configuration."""

from django.http import JsonResponse
from django.urls import path

from apps.alpha.interface import views

app_name = "alpha_api"

urlpatterns = [
    path(
        "",
        lambda request: JsonResponse(
            {
                "module": "alpha",
                "endpoints": [
                    "/api/alpha/scores/",
                    "/api/alpha/scores/upload/",
                    "/api/alpha/providers/status/",
                    "/api/alpha/universes/",
                    "/api/alpha/health/",
                    "/api/alpha/ops/inference/overview/",
                    "/api/alpha/ops/inference/trigger/",
                    "/api/alpha/ops/qlib-data/overview/",
                    "/api/alpha/ops/qlib-data/refresh/",
                ],
            }
        ),
        name="api-root",
    ),
    path("scores/", views.get_stock_scores, name="get_stock_scores"),
    path("scores/upload/", views.upload_scores, name="upload_scores"),
    path("providers/status/", views.get_provider_status, name="provider_status"),
    path("universes/", views.get_available_universes, name="available_universes"),
    path("health/", views.health_check, name="health_check"),
    path(
        "ops/inference/overview/",
        views.alpha_inference_ops_overview,
        name="ops-inference-overview",
    ),
    path(
        "ops/inference/trigger/",
        views.alpha_inference_ops_trigger,
        name="ops-inference-trigger",
    ),
    path(
        "ops/qlib-data/overview/",
        views.qlib_data_ops_overview,
        name="ops-qlib-data-overview",
    ),
    path(
        "ops/qlib-data/refresh/",
        views.qlib_data_ops_refresh,
        name="ops-qlib-data-refresh",
    ),
]
