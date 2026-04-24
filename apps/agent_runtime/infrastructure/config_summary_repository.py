"""Django read model for agent-runtime config summaries."""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from .models import AgentProposalModel, AgentTaskModel


class DjangoAgentRuntimeConfigSummaryRepository:
    """ORM-backed agent-runtime config-summary repository."""

    def get_operator_summary(self) -> dict[str, Any]:
        """Return operator queue and attention summary."""

        needs_attention_count = (
            AgentTaskModel._default_manager.filter(
                Q(requires_human=True) | Q(status__in=["needs_human", "failed"])
            )
            .distinct()
            .count()
        )
        pending_approval_count = AgentProposalModel._default_manager.filter(
            status__in=["generated", "submitted", "approved"]
        ).count()

        status = "configured"
        if needs_attention_count > 0 or pending_approval_count > 0:
            status = "attention"

        return {
            "status": status,
            "summary": {
                "total_tasks": AgentTaskModel._default_manager.count(),
                "needs_attention_count": needs_attention_count,
                "pending_approval_count": pending_approval_count,
                "operator_url": "/settings/agent-runtime/",
            },
        }
