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
]
