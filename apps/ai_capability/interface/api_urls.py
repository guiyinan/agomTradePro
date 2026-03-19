"""
AI Capability Catalog API URLs.
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .api_views import (
    CapabilityViewSet,
    catalog_stats,
    get_capability,
    list_capabilities,
    route_message,
    sync_capabilities,
)

router = DefaultRouter()
router.register(r"capabilities", CapabilityViewSet, basename="capability")

urlpatterns = [
    path("route/", route_message, name="ai-capability-route"),
    path("capabilities/", list_capabilities, name="ai-capability-list"),
    path("capabilities/<str:capability_key>/", get_capability, name="ai-capability-detail"),
    path("sync/", sync_capabilities, name="ai-capability-sync"),
    path("stats/", catalog_stats, name="ai-capability-stats"),
]

urlpatterns += router.urls
