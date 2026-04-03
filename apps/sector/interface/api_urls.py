"""
Sector API routes.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import SectorDataUpdateView, SectorRotationViewSet

app_name = "sector"

router = DefaultRouter()
router.register(r"", SectorRotationViewSet, basename="sector")

urlpatterns = [
    path("", include(router.urls)),
    path("update-data/", SectorDataUpdateView.as_view(), name="sector-update-data"),
]
