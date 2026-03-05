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
    # ========== API 路由（根路径，用于 /api/equity/ 挂载） ==========
    # DRF ViewSet 路由
    path('', include(router.urls)),

    # 多维度筛选 API（通用资产分析框架集成）
    path('multidim-screen/', EquityMultiDimScreenAPIView.as_view(), name='multidim_screen'),

    # ========== 页面路由（仅用于 /equity/ 页面挂载） ==========
    # 注意：以下页面路由仅在 /equity/ 前缀下有效
    # API 路由在 /api/equity/ 前缀下有效
]

# 页面路由（单独定义，用于 /equity/ 挂载）
page_urlpatterns = [
    path('screen/', screen_page, name='screen'),
    path('detail/<str:stock_code>/', detail_page, name='detail'),
    path('pool/', pool_page, name='pool'),
]

# 合并路由：API 优先，页面在后
urlpatterns = urlpatterns + page_urlpatterns
