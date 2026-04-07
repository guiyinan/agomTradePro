"""
AI Capability Catalog API URLs.
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .api_views import (
    CapabilityViewSet,
    api_root,
    catalog_stats,
    get_capability,
    list_capabilities,
    route_message,
    sync_capabilities,
    web_chat,
)

router = DefaultRouter()
router.register(r"capabilities", CapabilityViewSet, basename="capability")

urlpatterns = [
    path("", api_root, name="ai-capability-root"),
    path("route/", route_message, name="ai-capability-route"),
    path("web/", web_chat, name="ai-capability-web-chat"),
    path("capabilities/", list_capabilities, name="ai-capability-list"),
    path("capabilities/<str:capability_key>/", get_capability, name="ai-capability-detail"),
    path("sync/", sync_capabilities, name="ai-capability-sync"),
    path("stats/", catalog_stats, name="ai-capability-stats"),
]

urlpatterns += router.urls
