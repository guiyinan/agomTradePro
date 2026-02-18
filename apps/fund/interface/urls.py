"""
基金分析模块 - URL 配置
"""

from django.urls import path
from django.views.generic import RedirectView
from .views import (
    dashboard_view,
    ScreenFundsView,
    AnalyzeFundStyleView,
    CalculateFundPerformanceView,
    RankFundsView,
    FundInfoView,
    FundNavView,
    FundHoldingView,
    FundMultiDimScreenAPIView,
)

app_name = 'fund'

urlpatterns = [
    # 仪表盘页面
    path('dashboard/', dashboard_view, name='dashboard'),

    # 基金筛选
    path('screen/', ScreenFundsView.as_view(), name='screen'),

    # 基金排名
    path('rank/', RankFundsView.as_view(), name='rank'),

    # 基金风格分析
    path('style/<str:fund_code>/', AnalyzeFundStyleView.as_view(), name='style'),

    # 基金业绩计算
    path('performance/calculate/', CalculateFundPerformanceView.as_view(), name='calculate_performance'),

    # 基金信息
    path('info/<str:fund_code>/', FundInfoView.as_view(), name='info'),

    # 基金净值
    path('nav/<str:fund_code>/', FundNavView.as_view(), name='nav'),

    # 基金持仓
    path('holding/<str:fund_code>/', FundHoldingView.as_view(), name='holding'),

    # 向后兼容重定向
    path('multidim-screen/', RedirectView.as_view(url='/fund/api/multidim-screen/', permanent=False)),

    # ========== 多维度筛选 API（通用资产分析框架集成） ==========
    path('api/multidim-screen/', FundMultiDimScreenAPIView.as_view(), name='multidim_screen'),
]
