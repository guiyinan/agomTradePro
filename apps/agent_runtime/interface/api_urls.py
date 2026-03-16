"""
API URL Configuration for Agent Runtime.

FROZEN: Routes must not change.
See: docs/plans/ai-native/implementation-contract.md
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.agent_runtime.interface.views import (
    AgentTaskViewSet,
    AgentTaskHealthViewSet,
    AgentProposalViewSet,
    ContextSnapshotViewSet,
    OperatorDashboardViewSet,
)

# Router configuration
router = DefaultRouter()
router.register(r"tasks", AgentTaskViewSet, basename="task")
router.register(r"proposals", AgentProposalViewSet, basename="proposal")
router.register(r"context", ContextSnapshotViewSet, basename="context")
router.register(r"dashboard", OperatorDashboardViewSet, basename="dashboard")
router.register(r"health", AgentTaskHealthViewSet, basename="health")

# Task routes (frozen - implemented)
# - GET    /api/agent-runtime/tasks/              - List tasks
# - POST   /api/agent-runtime/tasks/              - Create task
# - GET    /api/agent-runtime/tasks/{id}/         - Get task detail
# - PUT    /api/agent-runtime/tasks/{id}/         - Update task
# - PATCH  /api/agent-runtime/tasks/{id}/         - Partial update
# - DELETE /api/agent-runtime/tasks/{id}/         - Delete task
# - GET    /api/agent-runtime/tasks/{id}/timeline/   - Get timeline events
# - GET    /api/agent-runtime/tasks/{id}/artifacts/  - Get artifacts
# - POST   /api/agent-runtime/tasks/{id}/resume/     - Resume task
# - POST   /api/agent-runtime/tasks/{id}/cancel/     - Cancel task
# - GET    /api/agent-runtime/tasks/needs_attention/ - Get tasks needing attention

# Health routes (frozen - implemented)
# - GET    /api/agent-runtime/health/             - Health check

# Proposal routes (frozen - M3 implemented)
# - POST   /api/agent-runtime/proposals/                      - Create proposal
# - GET    /api/agent-runtime/proposals/{id}/                 - Get proposal
# - POST   /api/agent-runtime/proposals/{id}/submit-approval/ - Submit for approval
# - POST   /api/agent-runtime/proposals/{id}/approve/         - Approve proposal
# - POST   /api/agent-runtime/proposals/{id}/reject/          - Reject proposal
# - POST   /api/agent-runtime/proposals/{id}/execute/         - Execute proposal

# Context routes (frozen - M2 implemented)
# - GET /api/agent-runtime/context/research/    - Research context snapshot
# - GET /api/agent-runtime/context/monitoring/  - Monitoring context snapshot
# - GET /api/agent-runtime/context/decision/    - Decision context snapshot
# - GET /api/agent-runtime/context/execution/   - Execution context snapshot
# - GET /api/agent-runtime/context/ops/         - Ops context snapshot

app_name = 'agent_runtime'

urlpatterns = [
    path('', include(router.urls)),
]
