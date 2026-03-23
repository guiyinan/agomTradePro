"""
Rotation Module Interface Layer - URL Configuration

URL patterns for the rotation module API and pages.
"""

from django.shortcuts import redirect
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.rotation.interface.views import (
    AssetClassViewSet,
    RotationActionViewSet,
    RotationConfigViewSet,
    RotationSignalViewSet,
    rotation_account_config_view,
    rotation_assets_view,
    rotation_configs_view,
    rotation_generate_signal_view,
    rotation_signals_view,
)

app_name = 'rotation'

# DRF API Router
router = DefaultRouter()
router.register(r'assets', AssetClassViewSet, basename='rotation-asset')
router.register(r'configs', RotationConfigViewSet, basename='rotation-config')
router.register(r'signals', RotationSignalViewSet, basename='rotation-signal')
router.register(r'', RotationActionViewSet, basename='rotation-action')


def rotation_home_redirect(request):
    """Redirect root /rotation/ to assets page"""
    return redirect('rotation:assets')


urlpatterns = [
    # Page routes
    path('', rotation_home_redirect, name='home'),
    path('assets/', rotation_assets_view, name='assets'),
    path('configs/', rotation_configs_view, name='configs'),
    path('signals/', rotation_signals_view, name='signals'),
    path('account-configs/', rotation_account_config_view, name='account_configs'),

    # Action routes
    path('generate-signal/', rotation_generate_signal_view, name='generate_signal'),

    # Note: API routes are now handled by api_urls.py mounted at /api/rotation/
    # The router is defined here for reference but not included to avoid duplication
]
