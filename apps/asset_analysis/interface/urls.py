"""
Asset analysis page routes.

页面路由与 API 路由分离：
- 页面路由保留在 urls.py
- DRF API 路由迁移到 api_urls.py
"""

from django.shortcuts import redirect
from django.urls import path

app_name = "asset_analysis"


def asset_analysis_root_redirect(request):
    """Redirect /asset-analysis/ to the canonical asset screen page."""
    return redirect("asset-screen")


def asset_pool_summary_redirect(request):
    """Redirect legacy pool summary page entry to the asset screen page."""
    return redirect("asset-screen")


def asset_pool_screen_redirect(request, asset_type: str):
    """Redirect legacy pool screen URLs to the unified asset screen page."""
    return redirect(f"/asset-analysis/screen/?asset_type={asset_type}")


urlpatterns = [
    path("", asset_analysis_root_redirect, name="root"),
    path("pool-summary/", asset_pool_summary_redirect, name="pool_summary"),
    path("screen/<str:asset_type>/", asset_pool_screen_redirect, name="pool_screen"),
]
