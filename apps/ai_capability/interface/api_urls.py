"""
AI Capability Catalog API URLs.
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .api_views import (
    CapabilityViewSet,
    api_root,
    catalog_stats,
    get_capability,
    list_capabilities,
    list_mcp_tools,
    mcp_tools_stats,
    route_message,
    sync_capabilities,
    sync_mcp_tools,
    toggle_mcp_tool,
    web_chat,
)
from .mcp_access_views import MCPAccessVerificationView
from .semantic_governance_views import (
    SemanticGovernanceApplyView,
    SemanticGovernanceAuditView,
    SemanticGovernancePreviewView,
    SemanticGovernanceView,
)

router = DefaultRouter()
router.register(r"capabilities", CapabilityViewSet, basename="capability")

urlpatterns = [
    path("", api_root, name="ai-capability-root"),
    path("route/", route_message, name="ai-capability-route"),
    path("web/", web_chat, name="ai-capability-web-chat"),
    path("capabilities/", list_capabilities, name="ai-capability-list"),
    path("capabilities/<str:capability_key>/", get_capability, name="ai-capability-detail"),
    path("sync/", sync_capabilities, name="ai-capability-sync"),
    path("stats/", catalog_stats, name="ai-capability-stats"),
    path("mcp-tools/", list_mcp_tools, name="ai-capability-mcp-tools"),
    path("mcp-tools/stats/", mcp_tools_stats, name="ai-capability-mcp-tools-stats"),
    path("mcp-tools/sync/", sync_mcp_tools, name="ai-capability-mcp-tools-sync"),
    path(
        "mcp-access/verify/",
        MCPAccessVerificationView.as_view(),
        name="mcp-access-verify",
    ),
    path(
        "mcp-tools/<str:capability_key>/toggle/<str:flag>/",
        toggle_mcp_tool,
        name="ai-capability-mcp-tool-toggle",
    ),
    path(
        "semantic-governance/",
        SemanticGovernanceView.as_view(),
        name="semantic-governance",
    ),
    path(
        "semantic-governance/preview/",
        SemanticGovernancePreviewView.as_view(),
        name="semantic-governance-preview",
    ),
    path(
        "semantic-governance/apply/",
        SemanticGovernanceApplyView.as_view(),
        name="semantic-governance-apply",
    ),
    path(
        "semantic-governance/audit/",
        SemanticGovernanceAuditView.as_view(),
        name="semantic-governance-audit",
    ),
]

urlpatterns += router.urls
