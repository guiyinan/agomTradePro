"""
Terminal API URL Configuration.

API路由配置。
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import (
    DeprecatedTerminalCommandViewSet,
    TerminalAuditView,
    TerminalChatView,
    TerminalChatStreamView,
    TerminalSessionView,
)

app_name = 'terminal_api'


router = DefaultRouter()
router.register(r'commands', DeprecatedTerminalCommandViewSet, basename='terminal-command')


urlpatterns = [
    path('', include(router.urls)),
    path('session/', TerminalSessionView.as_view(), name='terminal-session'),
    path('chat/', TerminalChatView.as_view(), name='terminal-chat'),
    path('chat/stream/', TerminalChatStreamView.as_view(), name='terminal-chat-stream'),
    path('audit/', TerminalAuditView.as_view(), name='terminal-audit'),
]
