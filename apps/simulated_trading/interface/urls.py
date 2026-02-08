"""
模拟盘交易模块 URL 配置
"""
from django.urls import path
from .views import (
    # 页面视图
    dashboard_page,
    account_detail_page,
    # 用户专属视图（重构）
    my_accounts_page,
    my_account_detail_page,
    my_positions_page,
    my_trades_page,
    # API 视图
    AccountListAPIView,
    AccountDetailAPIView,
    PositionListAPIView,
    TradeListAPIView,
    PerformanceAPIView,
    ManualTradeAPIView,
    FeeConfigListAPIView,
    EquityCurveAPIView,
    AutoTradingAPIView,
    DailyInspectionRunAPIView,
    DailyInspectionReportListAPIView,
)

app_name = 'simulated_trading'

urlpatterns = [
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

    # ============================================================================
    # API 路由
    # ============================================================================

    # 账户管理
    path('api/accounts/', AccountListAPIView.as_view(), name='account-list'),
    path('api/accounts/<int:account_id>/', AccountDetailAPIView.as_view(), name='account-detail-api'),

    # 持仓管理
    path('api/accounts/<int:account_id>/positions/', PositionListAPIView.as_view(), name='position-list'),

    # 交易记录
    path('api/accounts/<int:account_id>/trades/', TradeListAPIView.as_view(), name='trade-list'),

    # 绩效分析
    path('api/accounts/<int:account_id>/performance/', PerformanceAPIView.as_view(), name='performance'),

    # 手动交易
    path('api/accounts/<int:account_id>/trade/', ManualTradeAPIView.as_view(), name='manual-trade'),

    # 净值曲线
    path('api/accounts/<int:account_id>/equity-curve/', EquityCurveAPIView.as_view(), name='equity-curve'),

    # 费率配置
    path('api/fee-configs/', FeeConfigListAPIView.as_view(), name='fee-config-list'),

    # 自动交易
    path('api/auto-trading/run/', AutoTradingAPIView.as_view(), name='auto-trading-run'),

    # 日更巡检
    path('api/accounts/<int:account_id>/inspections/run/', DailyInspectionRunAPIView.as_view(), name='daily-inspection-run'),
    path('api/accounts/<int:account_id>/inspections/', DailyInspectionReportListAPIView.as_view(), name='daily-inspection-list'),
]
