"""Test-only URLConf exposing the retained Classic view for regression coverage."""

from django.urls import path

from apps.dashboard.interface.views import dashboard_view
from core.urls import urlpatterns as production_urlpatterns

urlpatterns = [
    *production_urlpatterns,
    path("__test__/legacy-dashboard/", dashboard_view, name="test_legacy_dashboard"),
]
