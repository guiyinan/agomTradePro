"""
URL configuration for Signal app.
"""
from django.urls import path, include
from . import views
from rest_framework.routers import DefaultRouter
from .api_views import SignalViewSet, SignalHealthView


app_name = 'signal'


# DRF API Router
router = DefaultRouter()
router.register(r'', SignalViewSet, basename='signal')


urlpatterns = [
    # Page routes
    path('manage/', views.signal_manage_view, name='manage'),

    # Signal actions
    path('create/', views.create_signal_view, name='create'),
    path('validate/', views.validate_signal_view, name='validate'),
    path('approve/', views.approve_signal_view, name='approve'),
    path('reject/', views.reject_signal_view, name='reject'),
    path('invalidate/', views.invalidate_signal_view, name='invalidate'),
    path('delete/<int:signal_id>/', views.delete_signal_view, name='delete'),
    path('eligibility/', views.signal_eligibility_info_view, name='eligibility'),

    # API routes
    path('api/', include(router.urls)),
    path('api/health/', SignalHealthView.as_view(), name='api_health'),
]
