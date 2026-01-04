"""
Account URL Configuration
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.account.interface import views
from apps.account.interface import api_views
from apps.account.interface import classification_api_views

app_name = 'account'

# API Router
router = DefaultRouter()
router.register(r'portfolios', api_views.PortfolioViewSet, basename='portfolio_api')
router.register(r'positions', api_views.PositionViewSet, basename='position_api')
router.register(r'transactions', api_views.TransactionViewSet, basename='transaction_api')
router.register(r'capital-flows', api_views.CapitalFlowViewSet, basename='capital_flow_api')
router.register(r'assets', api_views.AssetMetadataViewSet, basename='asset_api')

# Classification API Router
classification_router = DefaultRouter()
classification_router.register(r'categories', classification_api_views.AssetCategoryViewSet, basename='category_api')
classification_router.register(r'currencies', classification_api_views.CurrencyViewSet, basename='currency_api')
classification_router.register(r'exchange-rates', classification_api_views.ExchangeRateViewSet, basename='exchange_rate_api')

urlpatterns = [
    # 页面视图
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('settings/', views.settings_view, name='settings'),
    path('capital-flow/', views.capital_flow_view, name='capital_flow'),
    path('backtest/<int:backtest_id>/apply/', views.apply_backtest_results_view, name='apply_backtest'),

    # 管理员视图（用户管理）
    path('admin/users/', views.user_management_view, name='user_management'),
    path('admin/users/<int:user_id>/approve/', views.approve_user_view, name='approve_user'),
    path('admin/users/<int:user_id>/reject/', views.reject_user_view, name='reject_user'),
    path('admin/users/<int:user_id>/reset/', views.reset_user_status_view, name='reset_user_status'),
    path('admin/settings/', views.system_settings_view, name='system_settings'),

    # API 视图
    path('api/profile/', api_views.AccountProfileView.as_view(), name='api_profile'),
    path('api/health/', api_views.AccountHealthView.as_view(), name='api_health'),
    path('api/', include(router.urls)),
    path('api/volatility/', views.portfolio_volatility_api_view, name='api_volatility'),

    # 分类和汇率 API
    path('api/', include(classification_router.urls)),
    path('api/portfolios/<int:portfolio_id>/allocation/', classification_api_views.PortfolioAllocationView.as_view(), name='portfolio_allocation'),
]
