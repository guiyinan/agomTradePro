"""
Events URL Configuration

事件模块 URL 配置。
"""

from django.urls import path
from django.views.generic import RedirectView
from apps.events.interface import views

app_name = 'events'

urlpatterns = [
    # 向后兼容重定向 (旧路由重定向到新路由)
    path('publish/', RedirectView.as_view(url='/events/api/publish/', permanent=False)),
    path('query/', RedirectView.as_view(url='/events/api/query/', permanent=False)),
    path('metrics/', RedirectView.as_view(url='/events/api/metrics/', permanent=False)),
    path('status/', RedirectView.as_view(url='/events/api/status/', permanent=False)),
    path('replay/', RedirectView.as_view(url='/events/api/replay/', permanent=False)),

    # API 路由 - 事件发布
    path('api/publish/', views.EventPublishView.as_view(), name='publish'),

    # API 路由 - 事件查询
    path('api/query/', views.EventQueryView.as_view(), name='query'),

    # API 路由 - 事件指标
    path('api/metrics/', views.EventMetricsView.as_view(), name='metrics'),

    # API 路由 - 事件总线状态
    path('api/status/', views.EventBusStatusView.as_view(), name='status'),

    # API 路由 - 事件重放
    path('api/replay/', views.EventReplayView.as_view(), name='replay'),
]
