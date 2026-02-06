"""
Dashboard URL Configuration
"""

from django.urls import path
from apps.dashboard.interface import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_entry, name='index'),
    path('legacy/', views.dashboard_view, name='legacy'),

    # HTMX 端点
    path('position/<str:asset_code>/', views.position_detail_htmx, name='position_detail'),
    path('positions/', views.positions_list_htmx, name='positions_list'),
    path('api/allocation/', views.allocation_chart_htmx, name='allocation_api'),
    path('api/performance/', views.performance_chart_htmx, name='performance_api'),
    # Streamlit v1 API endpoints
    path('api/v1/summary/', views.dashboard_summary_v1, name='api_v1_summary'),
    path('api/v1/regime-quadrant/', views.regime_quadrant_v1, name='api_v1_regime_quadrant'),
    path('api/v1/equity-curve/', views.equity_curve_v1, name='api_v1_equity_curve'),
    path('api/v1/signal-status/', views.signal_status_v1, name='api_v1_signal_status'),

    # Alpha 可视化 HTMX 端点
    path('alpha/stocks/', views.alpha_stocks_htmx, name='alpha_stocks'),
    path('api/provider-status/', views.alpha_provider_status_htmx, name='alpha_provider_api'),
    path('api/coverage/', views.alpha_coverage_htmx, name='alpha_coverage_api'),
    path('api/ic-trends/', views.alpha_ic_trends_htmx, name='alpha_ic_trends_api'),
]
