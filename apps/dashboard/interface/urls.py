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

    # Backward-compatible API route names (keep template reverse() stable)
    path('api/position/<str:asset_code>/', views.position_detail_htmx, name='api_position_detail'),
    path('api/positions/', views.positions_list_htmx, name='api_positions_list'),
    path('api/allocation/', views.allocation_chart_htmx, name='api_allocation'),
    path('api/performance/', views.performance_chart_htmx, name='api_performance'),
    path('api/v1/summary/', views.dashboard_summary_v1, name='api_v1_summary'),
    path('api/v1/regime-quadrant/', views.regime_quadrant_v1, name='api_v1_regime_quadrant'),
    path('api/v1/equity-curve/', views.equity_curve_v1, name='api_v1_equity_curve'),
    path('api/v1/signal-status/', views.signal_status_v1, name='api_v1_signal_status'),
    path('api/alpha/stocks/', views.alpha_stocks_htmx, name='api_alpha_stocks'),
    path('api/alpha/factor-panel/', views.alpha_factor_panel_htmx, name='api_alpha_factor_panel'),
    path('api/alpha/provider-status/', views.alpha_provider_status_htmx, name='api_alpha_provider_status'),
    path('api/alpha/coverage/', views.alpha_coverage_htmx, name='api_alpha_coverage'),
    path('api/alpha/ic-trends/', views.alpha_ic_trends_htmx, name='api_alpha_ic_trends'),
    path('api/workflow/refresh-candidates/', views.workflow_refresh_candidates, name='api_workflow_refresh_candidates'),

    # Legacy API compatibility under /dashboard/api/*
    path('api/', include('apps.dashboard.interface.api_urls')),
]
