"""
API-only URL configuration for Signal app.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .api_views import SignalHealthView, SignalViewSet

app_name = "api_signal"

router = DefaultRouter()
router.register(r"", SignalViewSet, basename="signal")
router.register(r"unified", views.UnifiedSignalViewSet, basename="unified-signal")

urlpatterns = [
    path("health/", SignalHealthView.as_view(), name="health"),
    path("", include(router.urls)),
]
