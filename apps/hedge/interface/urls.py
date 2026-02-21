"""
Hedge Module Interface Layer - URL Configuration

URL patterns for the hedge module API.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.hedge.interface.views import (
    HedgePairViewSet,
    CorrelationHistoryViewSet,
    HedgePortfolioHoldingViewSet,
    HedgeAlertViewSet,
    HedgeActionViewSet,
)

app_name = 'hedge'

router = DefaultRouter()
router.register(r'pairs', HedgePairViewSet, basename='hedge-pair')
router.register(r'correlations', CorrelationHistoryViewSet, basename='hedge-correlation')
router.register(r'holdings', HedgePortfolioHoldingViewSet, basename='hedge-holding')
router.register(r'alerts', HedgeAlertViewSet, basename='hedge-alert')
router.register(r'actions', HedgeActionViewSet, basename='hedge-action')

urlpatterns = [
    # API routes - new standard format (when mounted under /api/hedge/)
    path('', include(router.urls)),

    # API routes - legacy format (backward compatibility when mounted under /hedge/)
    path('api/', include(router.urls)),
]
