"""
URL Configuration for Backtest Module.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# DRF Router
router = DefaultRouter()
router.register(r'api/backtests', views.BacktestViewSet, basename='backtest')

app_name = 'backtest'

urlpatterns = [
    # Page URLs
    path('', views.backtest_list_view, name='list'),
    path('create/', views.backtest_create_view, name='create'),
    path('<int:backtest_id>/', views.backtest_detail_view, name='detail'),

    # API URLs (non-DRF)
    path('api/statistics/', views.backtest_statistics_api_view, name='statistics-api'),
    path('api/run/', views.run_backtest_api_view, name='run-api'),

    # DRF URLs
    path('', include(router.urls)),
]
