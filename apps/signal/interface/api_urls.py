"""
API-only URL configuration for Signal app.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .api_views import SignalHealthView, SignalViewSet
from .forecast_api_views import (
    ForecastEntryCreateView,
    ForecastEvaluationCreateView,
    ForecastOutcomeCreateView,
)

app_name = "api_signal"

router = DefaultRouter()
router.register(r"", SignalViewSet, basename="signal")
router.register(r"unified", views.UnifiedSignalViewSet, basename="unified-signal")

urlpatterns = [
    path("health/", SignalHealthView.as_view(), name="health"),
    path("forecast-ledger/", ForecastEntryCreateView.as_view(), name="forecast-entry-create"),
    path(
        "forecast-ledger/<str:entry_id>/evaluations/",
        ForecastEvaluationCreateView.as_view(),
        name="forecast-evaluation-create",
    ),
    path(
        "forecast-ledger/<str:entry_id>/outcome/",
        ForecastOutcomeCreateView.as_view(),
        name="forecast-outcome-create",
    ),
    path("", include(router.urls)),
]
