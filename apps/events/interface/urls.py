"""
Events URL Configuration

事件模块 URL 配置。
"""

from django.urls import path
from apps.events.interface import views

app_name = 'events'

urlpatterns = [
    # 事件发布
    path('publish/', views.EventPublishView.as_view(), name='publish'),

    # 事件查询
    path('query/', views.EventQueryView.as_view(), name='query'),

    # 事件指标
    path('metrics/', views.EventMetricsView.as_view(), name='metrics'),

    # 事件总线状态
    path('status/', views.EventBusStatusView.as_view(), name='status'),

    # 事件重放
    path('replay/', views.EventReplayView.as_view(), name='replay'),
]
