"""
Rotation Module Interface Layer - URL Configuration

URL patterns for the rotation module API.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.rotation.interface.views import (
    AssetClassViewSet,
    RotationConfigViewSet,
    RotationSignalViewSet,
    RotationActionViewSet,
)

app_name = 'rotation'

router = DefaultRouter()
router.register(r'assets', AssetClassViewSet, basename='rotation-asset')
router.register(r'configs', RotationConfigViewSet, basename='rotation-config')
router.register(r'signals', RotationSignalViewSet, basename='rotation-signal')
router.register(r'', RotationActionViewSet, basename='rotation-action')

urlpatterns = [
    # API routes - new standard format (when mounted under /api/rotation/)
    path('', include(router.urls)),

    # API routes - legacy format (backward compatibility when mounted under /rotation/)
    path('api/', include(router.urls)),
]
