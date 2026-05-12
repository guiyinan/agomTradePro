"""
Hedge Module Interface Layer - URL Configuration

URL patterns for the hedge module API and pages.
"""

from django.shortcuts import redirect
from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.hedge.interface.views import (
    CorrelationHistoryViewSet,
    HedgeActionViewSet,
    HedgeAlertViewSet,
    HedgePairViewSet,
    HedgePortfolioSnapshotViewSet,
    # Action views
    activate_pair_view,
    deactivate_pair_view,
    hedge_alerts_view,
    # Page views
    hedge_pairs_view,
    hedge_snapshots_view,
    resolve_alert_view,
    run_monitoring_view,
    update_portfolios_view,
)

app_name = 'hedge'


# DRF API Router
router = DefaultRouter()
router.register(r'pairs', HedgePairViewSet, basename='hedge-pair')
router.register(r'correlations', CorrelationHistoryViewSet, basename='hedge-correlation')
router.register(r'snapshots', HedgePortfolioSnapshotViewSet, basename='hedge-snapshot')
router.register(r'alerts', HedgeAlertViewSet, basename='hedge-alert')
router.register(r'actions', HedgeActionViewSet, basename='hedge-action')


def hedge_home_redirect(request):
    """Redirect root /hedge/ to pairs page"""
    return redirect('hedge:pairs')


urlpatterns = [
    # Page routes
    path('', hedge_home_redirect, name='home'),
    path('pairs/', hedge_pairs_view, name='pairs'),
    path('snapshots/', hedge_snapshots_view, name='snapshots'),
    path('alerts/', hedge_alerts_view, name='alerts'),

    # Action routes
    path('pairs/<int:pair_id>/activate/', activate_pair_view, name='activate_pair'),
    path('pairs/<int:pair_id>/deactivate/', deactivate_pair_view, name='deactivate_pair'),
    path('portfolios/update/', update_portfolios_view, name='update_portfolios'),
    path('monitoring/run/', run_monitoring_view, name='run_monitoring'),
    path('alerts/<int:alert_id>/resolve/', resolve_alert_view, name='resolve_alert'),

    # Note: API routes are now handled by api_urls.py mounted at /api/hedge/
    # The router is defined here for reference but not included to avoid duplication
]
