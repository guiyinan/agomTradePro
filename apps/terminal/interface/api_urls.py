"""
Terminal API URL Configuration.

API路由配置。
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import (
    TerminalAuditView,
    TerminalChatView,
    TerminalCommandViewSet,
    TerminalSessionView,
)

app_name = 'terminal_api'


router = DefaultRouter()
router.register(r'commands', TerminalCommandViewSet, basename='terminal-command')


urlpatterns = [
    path('', include(router.urls)),
    path('session/', TerminalSessionView.as_view(), name='terminal-session'),
    path('chat/', TerminalChatView.as_view(), name='terminal-chat'),
    path('audit/', TerminalAuditView.as_view(), name='terminal-audit'),
]
