"""
基金分析模块 - URL 配置
"""

from django.urls import include, path
from django.views.generic import RedirectView

from .views import (
    dashboard_view,
    FundMultiDimScreenAPIView,
)

app_name = 'fund'

urlpatterns = [
    # 仪表盘页面
    path('dashboard/', dashboard_view, name='dashboard'),

    # Legacy compatibility
    path('multidim-screen/', RedirectView.as_view(url='/fund/api/multidim-screen/', permanent=False)),
    path('api/multidim-screen/', FundMultiDimScreenAPIView.as_view(), name='multidim_screen_page'),

    # Legacy API compatibility under /fund/api/*
    path('api/', include('apps.fund.interface.api_urls')),
]
