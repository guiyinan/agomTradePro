"""Regime API URL configuration."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import RegimeActionView, RegimeHealthView, RegimeNavigatorView, RegimeViewSet

app_name = "regime_api"

router = DefaultRouter()
router.register(r"", RegimeViewSet, basename="regime")

urlpatterns = [
    path("", include(router.urls)),
    path("health/", RegimeHealthView.as_view(), name="health"),
    path("navigator/", RegimeNavigatorView.as_view(), name="regime-navigator"),
    path("action/", RegimeActionView.as_view(), name="regime-action"),
]

