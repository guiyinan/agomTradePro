"""
Market Data 模块 - 页面视图

只做页面渲染，数据由前端 JS 通过 API 获取。
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from core.application.provider_inventory import (
    build_provider_dashboard as _build_provider_dashboard,
)


def build_provider_dashboard() -> dict[str, object]:
    """兼容旧调用入口，实际逻辑已合并到统一数据源中心。"""
    return _build_provider_dashboard()


@login_required
@require_http_methods(["GET"])
def providers_page(request):
    """市场数据源状态入口已并入统一数据源中心。"""
    return redirect(f"{reverse('macro:datasources')}#provider-status")
