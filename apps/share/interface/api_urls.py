"""
Share API URL Configuration

API 路由配置。
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.share.interface.views import PublicShareViewSet, ShareLinkViewSet

app_name = "share_api"

router = DefaultRouter()
router.register(r"links", ShareLinkViewSet, basename="share_link")

# 公开访问路由（不使用标准的 router 格式）
public_patterns = [
    # 通过短码访问分享链接
    path("public/<str:short_code>/", PublicShareViewSet.as_view({"get": "retrieve"}), name="public_get"),
    # 访问分享（带密码验证）
    path("public/<str:short_code>/access/", PublicShareViewSet.as_view({"post": "access"}), name="public_access"),
    # 获取快照
    path("public/<str:short_code>/snapshot/", PublicShareViewSet.as_view({"get": "snapshot"}), name="public_snapshot"),
]

urlpatterns = [
    path("", include(router.urls)),
    path("", include(public_patterns)),
]
