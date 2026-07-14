"""
Terminal API URL Configuration.

API路由配置。
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import (
    DeprecatedTerminalCommandViewSet,
    TerminalApprovalDecisionView,
    TerminalAuditView,
    TerminalChatStreamView,
    TerminalChatView,
    TerminalSessionView,
    TuiAgentActionSchemaView,
    TuiAgentActionSearchView,
)

app_name = 'terminal_api'


router = DefaultRouter()
router.register(r'commands', DeprecatedTerminalCommandViewSet, basename='terminal-command')


urlpatterns = [
    path('', include(router.urls)),
    path('session/', TerminalSessionView.as_view(), name='terminal-session'),
    path('chat/', TerminalChatView.as_view(), name='terminal-chat'),
    path('chat/stream/', TerminalChatStreamView.as_view(), name='terminal-chat-stream'),
    path(
        'approvals/<int:proposal_id>/decision/',
        TerminalApprovalDecisionView.as_view(),
        name='terminal-approval-decision',
    ),
    path('audit/', TerminalAuditView.as_view(), name='terminal-audit'),
    path(
        'tui/actions/search/',
        TuiAgentActionSearchView.as_view(),
        name='tui-agent-action-search',
    ),
    path(
        'tui/actions/<path:action_key>/schema/',
        TuiAgentActionSchemaView.as_view(),
        name='tui-agent-action-schema',
    ),
]
