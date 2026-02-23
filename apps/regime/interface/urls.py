"""
URL configuration for Regime app.
"""
from django.urls import path, include
from django.shortcuts import redirect
from . import views
from rest_framework.routers import DefaultRouter
from .api_views import RegimeViewSet, RegimeHealthView


app_name = 'regime'


# DRF API Router
router = DefaultRouter()
router.register(r'', RegimeViewSet, basename='regime')


def regime_home_redirect(request):
    """Redirect root /regime/ to dashboard"""
    return redirect('regime:dashboard')


urlpatterns = [
    # Root route - redirect to dashboard
    path('', regime_home_redirect, name='home'),

    # Page routes
    path('dashboard/', views.regime_dashboard_view, name='dashboard'),
    path('clear-cache/', views.clear_regime_cache, name='clear_cache'),

    # API routes - new standard format (when mounted under /api/regime/)
    path('', include(router.urls)),
    path('health/', RegimeHealthView.as_view(), name='health'),

    # API routes - legacy format (backward compatibility when mounted under /regime/)
    path('api/', include(router.urls)),
    path('api/health/', RegimeHealthView.as_view(), name='health_legacy'),
]
