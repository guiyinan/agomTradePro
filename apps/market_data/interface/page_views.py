"""
Market Data 模块 - 页面视图

只做页面渲染，数据由前端 JS 通过 API 获取。
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods


@login_required
@require_http_methods(["GET"])
def providers_page(request):
    """市场数据源管理页面

    GET /market-data/providers/
    """
    return render(request, "market_data/providers.html")
