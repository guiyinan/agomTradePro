"""
URL Configuration for AI Prompt Management.

Defines URL patterns for the prompt module API.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PromptTemplateViewSet,
    ChainConfigViewSet,
    ReportGenerationView,
    SignalGenerationView,
    ChatView,
    ChatProvidersView,
    ChatModelsView,
    ExecutionLogViewSet,
    prompt_manage_view
)

app_name = 'prompt'

# 创建路由器
router = DefaultRouter()
router.register(r'templates', PromptTemplateViewSet, basename='prompt-template')
router.register(r'chains', ChainConfigViewSet, basename='chain-config')
router.register(r'logs', ExecutionLogViewSet, basename='execution-log')

# URL模式
urlpatterns = [
    # 页面路由
    path('manage/', prompt_manage_view, name='prompt-manage'),

    # API路由
    path('api/', include(router.urls)),

    # 报告生成
    path('api/reports/generate', ReportGenerationView.as_view(), name='generate-report'),

    # 信号生成
    path('api/signals/generate', SignalGenerationView.as_view(), name='generate-signal'),

    # 聊天
    path('api/chat', ChatView.as_view(), name='chat'),
    path('api/chat/providers', ChatProvidersView.as_view(), name='chat-providers'),
    path('api/chat/models', ChatModelsView.as_view(), name='chat-models'),
]
