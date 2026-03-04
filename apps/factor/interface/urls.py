"""
Factor Module Interface Layer - URL Configuration

URL patterns for the factor module API and pages.
"""

from django.urls import path, include
from django.shortcuts import redirect
from rest_framework.routers import DefaultRouter

from apps.factor.interface.views import (
    FactorDefinitionViewSet,
    FactorPortfolioConfigViewSet,
    FactorScoreViewSet,
    FactorActionViewSet,
    # Page views
    factor_home_redirect,
    factor_manage_view,
    portfolio_list_view,
    factor_calculate_view,
    create_portfolio_config_view,
    portfolio_config_action_view,
    calculate_scores_view,
    explain_stock_view,
)

app_name = 'factor'

router = DefaultRouter()
router.register(r'definitions', FactorDefinitionViewSet, basename='factor-definition')
router.register(r'configs', FactorPortfolioConfigViewSet, basename='factor-config')
router.register(r'', FactorActionViewSet, basename='factor-action')


def factor_api_home_redirect(request):
    """Redirect root /api/factor/ to docs/info"""
    from django.http import JsonResponse
    return JsonResponse({
        'message': 'AgomSAAF Factor Module API',
        'endpoints': {
            'definitions': '/api/factor/definitions/',
            'configs': '/api/factor/configs/',
            'actions': '/api/factor/',
        }
    })


urlpatterns = [
    # Page routes
    path('', factor_home_redirect, name='home'),
    path('manage/', factor_manage_view, name='manage'),
    path('portfolios/', portfolio_list_view, name='portfolios'),
    path('calculate/', factor_calculate_view, name='calculate'),

    # Page action routes
    path('portfolio/create/', create_portfolio_config_view, name='create_config'),
    path('portfolio/<int:config_id>/', portfolio_config_action_view, name='config_action'),
    path('calculate/scores/', calculate_scores_view, name='calculate_scores'),
    path('explain/<str:stock_code>/', explain_stock_view, name='explain_stock'),

    # API routes - legacy format (backward compatibility when mounted under /factor/)
    path('api/', include(router.urls)),
    path('health/', factor_api_home_redirect, name='health'),
]
