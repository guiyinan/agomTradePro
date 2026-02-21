"""
Factor Module Interface Layer - URL Configuration

URL patterns for the factor module API.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.factor.interface.views import (
    FactorDefinitionViewSet,
    FactorPortfolioConfigViewSet,
    FactorScoreViewSet,
    FactorActionViewSet,
)

app_name = 'factor'

router = DefaultRouter()
router.register(r'definitions', FactorDefinitionViewSet, basename='factor-definition')
router.register(r'configs', FactorPortfolioConfigViewSet, basename='factor-config')
router.register(r'', FactorActionViewSet, basename='factor-action')

urlpatterns = [
    # API routes - new standard format (when mounted under /api/factor/)
    path('', include(router.urls)),

    # API routes - legacy format (backward compatibility when mounted under /factor/)
    path('api/', include(router.urls)),
]
