"""基金分析模块页面路由。"""

from django.urls import path
from django.views.generic import RedirectView

from .views import dashboard_view

app_name = 'fund'

urlpatterns = [
    path("", RedirectView.as_view(url="/fund/dashboard/", permanent=False), name="home"),
    # 仪表盘页面
    path('dashboard/', dashboard_view, name='dashboard'),
]
