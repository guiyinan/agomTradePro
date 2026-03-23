"""
URL configuration for Signal app.
"""
from django.shortcuts import redirect
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .api_views import SignalHealthView, SignalViewSet

app_name = 'signal'


# DRF API Router
router = DefaultRouter()
router.register(r'', SignalViewSet, basename='signal')
router.register(r'unified', views.UnifiedSignalViewSet, basename='unified-signal')


def signal_home_redirect(request):
    """Redirect root /signal/ to manage page"""
    return redirect('signal:manage')


urlpatterns = [
    # Root route - redirect to manage page
    path('', signal_home_redirect, name='home'),

    # Page routes
    path('manage/', views.signal_manage_view, name='manage'),
    path('list/', views.signal_manage_view, name='list_legacy'),

    # Signal actions
    path('create/', views.create_signal_view, name='create'),
    path('approve/', views.approve_signal_view, name='approve'),
    path('reject/', views.reject_signal_view, name='reject'),
    path('invalidate/', views.invalidate_signal_view, name='invalidate'),
    path('delete/<int:signal_id>/', views.delete_signal_view, name='delete'),
    path('check/<int:signal_id>/', views.check_invalidation_view, name='check'),
    path('batch-check/', views.run_batch_check_view, name='batch_check'),
    path('list/validate/', views.run_batch_check_view, name='list_validate_legacy'),
    path('eligibility/', views.signal_eligibility_info_view, name='eligibility'),

    # AI Assistant routes
    path('ai/parse-logic/', views.ai_parse_logic_view, name='ai_parse_logic'),
    path('ai/indicators/', views.get_indicators_view, name='ai_indicators'),

    # API routes - new standard format (when mounted under /api/signal/)
    # Health check must come BEFORE router to avoid being caught by the router
    path('health/', SignalHealthView.as_view(), name='health'),
    path('', include(router.urls)),
]
