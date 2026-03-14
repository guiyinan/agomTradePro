"""模拟盘交易模块 URL 配置。"""
from django.shortcuts import redirect
from django.urls import include, path
from .views import (
    # 页面视图
    dashboard_page,
    account_detail_page,
    # 用户专属视图（重构）
    my_accounts_page,
    my_account_detail_page,
    my_positions_page,
    my_trades_page,
    my_inspection_notify_page,
)

app_name = 'simulated_trading'

urlpatterns = [
    path('', lambda request: redirect('simulated_trading:my-accounts'), name='home'),

    # ============================================================================
    # 页面路由
    # ============================================================================
    path('dashboard/', dashboard_page, name='dashboard'),
    path('accounts/<int:account_id>/', account_detail_page, name='account-detail'),

    # ⭐ 用户投资组合路由（重构：使用 account_id 替代 account_type）
    path('my-accounts/', my_accounts_page, name='my-accounts'),
    path('my-accounts/<int:account_id>/', my_account_detail_page, name='my-account-detail'),
    path('my-accounts/<int:account_id>/positions/', my_positions_page, name='my-positions'),
    path('my-accounts/<int:account_id>/trades/', my_trades_page, name='my-trades'),
    path('my-accounts/<int:account_id>/inspection-notify/', my_inspection_notify_page, name='my-inspection-notify'),

    # Legacy API compatibility under /simulated-trading/api/*
    path('api/', include(('apps.simulated_trading.interface.api_urls', 'simulated_trading_api'), namespace='legacy_simulated_trading_api')),
]
