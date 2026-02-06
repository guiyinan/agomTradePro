"""
Dashboard URL Configuration
"""

from django.urls import path
from apps.dashboard.interface import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_view, name='index'),

    # HTMX 端点
    path('position/<str:asset_code>/', views.position_detail_htmx, name='position_detail'),
    path('positions/', views.positions_list_htmx, name='positions_list'),
    path('api/allocation/', views.allocation_chart_htmx, name='allocation_api'),
    path('api/performance/', views.performance_chart_htmx, name='performance_api'),

    # Alpha 可视化 HTMX 端点
    path('alpha/stocks/', views.alpha_stocks_htmx, name='alpha_stocks'),
    path('api/provider-status/', views.alpha_provider_status_htmx, name='alpha_provider_api'),
    path('api/coverage/', views.alpha_coverage_htmx, name='alpha_coverage_api'),
    path('api/ic-trends/', views.alpha_ic_trends_htmx, name='alpha_ic_trends_api'),
]
