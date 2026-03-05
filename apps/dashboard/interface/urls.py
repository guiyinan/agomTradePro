"""
Dashboard URL Configuration
"""

from django.urls import include, path
from django.views.generic import RedirectView
from apps.dashboard.interface import views

app_name = 'dashboard'

urlpatterns = [
    # Page routes
    path('', views.dashboard_entry, name='index'),
    path('ops-center/', RedirectView.as_view(url='/ops/', permanent=False), name='ops-center'),

    # Backward-compatible redirects
    path('position/<str:asset_code>/', RedirectView.as_view(url='/dashboard/api/position/%(asset_code)s/', permanent=False), name='position_detail'),
    path('positions/', RedirectView.as_view(url='/dashboard/api/positions/', permanent=False), name='positions_list'),
    path('alpha/stocks/', RedirectView.as_view(url='/dashboard/api/alpha/stocks/', permanent=False), name='alpha_stocks'),

    # Legacy API compatibility under /dashboard/api/*
    path('api/', include('apps.dashboard.interface.api_urls')),
]
