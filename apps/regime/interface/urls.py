"""URL configuration for Regime app."""
from django.urls import path, include
from django.shortcuts import redirect
from . import views


app_name = 'regime'


def regime_home_redirect(request):
    """Redirect root /regime/ to dashboard"""
    return redirect('regime:dashboard')


urlpatterns = [
    # Root route - redirect to dashboard
    path('', regime_home_redirect, name='home'),

    # Page routes
    path('dashboard/', views.regime_dashboard_view, name='dashboard'),
    path('clear-cache/', views.clear_regime_cache, name='clear_cache'),

    # Legacy API compatibility under /regime/api/*
    path('api/', include(('apps.regime.interface.api_urls', 'regime_api'), namespace='legacy_regime_api')),
]
