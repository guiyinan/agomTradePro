"""
板块分析模块 - URL 路由配置
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import SectorDataUpdateView, SectorRotationViewSet

# Router for ViewSet
router = DefaultRouter()
router.register(r'', SectorRotationViewSet, basename='sector')

urlpatterns = [
    # ViewSet 路由
    path('', include(router.urls)),

    # 单独的 API 路由
    path('update-data/', SectorDataUpdateView.as_view(), name='sector-update-data'),
]

# URL 列表：
# POST /api/sector/analyze/       - 分析板块轮动
# GET  /api/sector/rotation/      - 获取板块轮动推荐
# POST /api/sector/update-data/   - 更新板块数据
