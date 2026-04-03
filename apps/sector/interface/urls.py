"""
Sector page routes.

板块分析的用户入口已收口到 rotation 页面，旧 sector 页面路径仅保留跳转。
"""

from django.shortcuts import redirect
from django.urls import path

app_name = "sector"


def sector_page_redirect(request):
    """Redirect legacy sector pages to the rotation assets page."""
    return redirect("rotation:assets")


urlpatterns = [
    path("", sector_page_redirect, name="sector-home"),
    path("analysis/", sector_page_redirect, name="sector-analysis"),
    path("rotation/", sector_page_redirect, name="sector-rotation"),
    path("strength/", sector_page_redirect, name="sector-strength"),
    path("flow/", sector_page_redirect, name="sector-flow"),
]
