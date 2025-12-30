"""
URL configuration for Regime app.
"""
from django.urls import path, include
from . import views
from rest_framework.routers import DefaultRouter
from .api_views import RegimeViewSet, RegimeHealthView


app_name = 'regime'


# DRF API Router
router = DefaultRouter()
router.register(r'', RegimeViewSet, basename='regime')


urlpatterns = [
    # Page routes
    path('dashboard/', views.regime_dashboard_view, name='dashboard'),

    # API routes
    path('api/', include(router.urls)),
    path('api/health/', RegimeHealthView.as_view(), name='api_health'),
]
