"""基金分析模块页面路由。"""

from django.urls import path
from django.views.generic import RedirectView

from .views import dashboard_view

app_name = 'fund'

urlpatterns = [
    # 仪表盘页面
    path('dashboard/', dashboard_view, name='dashboard'),

    # 兼容旧入口，跳转到统一 API 前缀
    path(
        'multidim-screen/',
        RedirectView.as_view(url='/api/fund/multidim-screen/', permanent=False),
        name='multidim_screen_page',
    ),
]
