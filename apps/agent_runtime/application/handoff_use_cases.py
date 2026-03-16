"""
Application Use Cases for Task Handoff.

WP-M4-02: Resume and handoff behavior.
"""

import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from django.utils import timezone

from apps.agent_runtime.domain.entities import (
    AgentTask,
    TaskStatus,
    EventSource,
)
from apps.agent_runtime.application.services import TimelineEventWriterService


logger = logging.getLogger(__name__)


@dataclass
class HandoffInput:
    task_id: int
    to_agent: str
    handoff_reason: str
    recommended_next_action: Optional[str] = None
    open_risks: Optional[List[str]] = None
    actor: Optional[Dict[str, Any]] = None


@dataclass
class HandoffOutput:
    task_id: int
    request_id: str
    handoff_id: int
    handoff_payload: Dict[str, Any]


class HandoffTaskUseCase:
    """
    Hand a task to another agent or human with a complete context package.

    The handoff payload includes:
    - current status
    - completed steps
    - pending steps
    - latest context references
    - open risks
    - recommended next actor
    """

    def __init__(
        self,
        timeline_service: Optional[TimelineEventWriterService] = None,
    ):
        self.timeline_service = timeline_service or TimelineEventWriterService()

    def execute(self, inp: HandoffInput) -> HandoffOutput:
        from apps.agent_runtime.infrastructure.models import (
            AgentTaskModel,
            AgentTaskStepModel,
            AgentHandoffModel,
            AgentContextSnapshotModel,
            AgentProposalModel,
        )

        task_model = AgentTaskModel._default_manager.get(pk=inp.task_id)

        # Gather completed and pending steps
        steps = AgentTaskStepModel._default_manager.filter(
            task_id=task_model.id
        ).order_by("step_index")

        completed_steps = [
            {"step_key": s.step_key, "step_name": s.step_name, "status": s.status}
            for s in steps if s.status == "completed"
        ]
        pending_steps = [
            {"step_key": s.step_key, "step_name": s.step_name, "status": s.status}
            for s in steps if s.status != "completed"
        ]

        # Latest context snapshot
        context_ref = None
        snapshot = AgentContextSnapshotModel._default_manager.filter(
            task_id=task_model.id
        ).order_by("-created_at").first()
        if snapshot:
            context_ref = {
                "snapshot_id": snapshot.id,
                "domain": snapshot.domain,
                "generated_at": snapshot.generated_at.isoformat() if snapshot.generated_at else None,
            }

        # Open proposals
        open_proposals = list(
            AgentProposalModel._default_manager.filter(
                task_id=task_model.id,
            ).exclude(
                status__in=["executed", "expired"],
            ).values("id", "proposal_type", "status", "risk_level")
        )

        # Build handoff payload
        handoff_payload = {
            "current_status": task_model.status,
            "task_domain": task_model.task_domain,
            "task_type": task_model.task_type,
            "completed_steps": completed_steps,
            "pending_steps": pending_steps,
            "latest_context_reference": context_ref,
            "open_proposals": open_proposals,
            "open_risks": inp.open_risks or [],
            "recommended_next_actor": inp.to_agent,
            "recommended_next_action": inp.recommended_next_action,
        }

        # Create handoff record
        handoff_model = AgentHandoffModel._default_manager.create(
            request_id=task_model.request_id,
            task_id=task_model.id,
            from_agent=inp.actor.get("agent_id", "system") if inp.actor else "system",
            to_agent=inp.to_agent,
            handoff_reason=inp.handoff_reason,
            handoff_payload=handoff_payload,
            handoff_status="completed",
        )

        # Timeline event
        self.timeline_service.write_task_escalated_event(
            task=task_model.id,
            reason=inp.handoff_reason,
            event_source=EventSource.SYSTEM,
            actor=inp.actor,
            escalation_target=inp.to_agent,
        )

        return HandoffOutput(
            task_id=task_model.id,
            request_id=task_model.request_id,
            handoff_id=handoff_model.id,
            handoff_payload=handoff_payload,
        )
