"""
URL configuration for Filter app.
"""
from django.urls import path, include
from . import views
from rest_framework.routers import DefaultRouter
from .api_views import FilterViewSet, FilterHealthView


app_name = 'filter'


# DRF API Router
router = DefaultRouter()
router.register(r'', FilterViewSet, basename='filter')


urlpatterns = [
    # Page routes
    path('dashboard/', views.filter_dashboard_view, name='dashboard'),

    # API routes
    path('api/', include(router.urls)),
    path('api/health/', FilterHealthView.as_view(), name='api_health'),
]
