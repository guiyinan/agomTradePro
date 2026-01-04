"""
个股分析模块 URL 配置

包含：
- API 路由（DRF ViewSet）
- 页面路由（Django Views）
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import EquityViewSet, screen_page, detail_page, pool_page, EquityMultiDimScreenAPIView

app_name = 'equity'

# API Router
router = DefaultRouter()
router.register(r'', EquityViewSet, basename='equity')

urlpatterns = [
    # API 路由
    path('api/', include(router.urls)),

    # ========== 多维度筛选 API（通用资产分析框架集成） ==========
    path('api/multidim-screen/', EquityMultiDimScreenAPIView.as_view(), name='multidim_screen'),

    # 页面路由
    path('screen/', screen_page, name='screen'),
    path('detail/<str:stock_code>/', detail_page, name='detail'),
    path('pool/', pool_page, name='pool'),
]
