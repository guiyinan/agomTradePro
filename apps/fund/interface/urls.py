"""
基金分析模块 - URL 配置
"""

from django.urls import path
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter
from rest_framework.response import Response
from rest_framework.views import APIView

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


# 基金列表 API（根路径）
class FundListAPIView(APIView):
    """基金列表 API - 返回可用的基金操作端点"""
    def get(self, request):
        return Response({
            'endpoints': {
                'screen': '/api/fund/screen/',
                'rank': '/api/fund/rank/',
                'style': '/api/fund/style/{fund_code}/',
                'performance': '/api/fund/performance/calculate/',
                'info': '/api/fund/info/{fund_code}/',
                'nav': '/api/fund/nav/{fund_code}/',
                'holding': '/api/fund/holding/{fund_code}/',
                'multidim_screen': '/api/fund/multidim-screen/',
            }
        })


# API Router（用于 /api/fund/ 挂载）
api_urlpatterns = [
    # 根路径 - 返回可用端点列表
    path('', FundListAPIView.as_view(), name='api-root'),

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

    # 多维度筛选 API
    path('multidim-screen/', FundMultiDimScreenAPIView.as_view(), name='multidim_screen'),
]

# 页面路由（用于 /fund/ 挂载）
page_urlpatterns = [
    # 仪表盘页面
    path('dashboard/', dashboard_view, name='dashboard'),

    # 向后兼容重定向
    path('multidim-screen/', RedirectView.as_view(url='/fund/api/multidim-screen/', permanent=False)),

    # API 路由（页面路由下也保留）
    path('api/multidim-screen/', FundMultiDimScreenAPIView.as_view(), name='multidim_screen_page'),
]

# 合并路由
urlpatterns = api_urlpatterns + page_urlpatterns
