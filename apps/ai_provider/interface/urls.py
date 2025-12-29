"""
URL Configuration for AI Provider Management.

URL路由配置。
"""

from django.urls import path
from . import views

app_name = 'ai_provider'

urlpatterns = [
    # 管理页面
    path('', views.page_views.ai_manage_view, name='manage'),
    path('logs/', views.page_views.ai_usage_logs_view, name='logs'),
    path('detail/<int:provider_id>/', views.page_views.ai_provider_detail_view, name='detail'),
]
