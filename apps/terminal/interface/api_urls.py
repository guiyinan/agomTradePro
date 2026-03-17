"""
Terminal API URL Configuration.

API路由配置。
"""

from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .api_views import TerminalCommandViewSet, TerminalSessionView

app_name = 'terminal_api'


router = DefaultRouter()
router.register(r'commands', TerminalCommandViewSet, basename='terminal-command')


urlpatterns = [
    path('', include(router.urls)),
    path('session/', TerminalSessionView.as_view(), name='terminal-session'),
]
