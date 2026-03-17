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
from apps.agent_runtime.domain.entities import TERMINAL_PROPOSAL_STATUSES
from apps.agent_runtime.infrastructure.repositories import (
    AgentContextRepository,
    AgentHandoffRepository,
    AgentProposalRepository,
    AgentTaskRepository,
)


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
        task_repo: Optional[AgentTaskRepository] = None,
        context_repo: Optional[AgentContextRepository] = None,
        proposal_repo: Optional[AgentProposalRepository] = None,
        handoff_repo: Optional[AgentHandoffRepository] = None,
    ):
        self.timeline_service = timeline_service or TimelineEventWriterService()
        self.task_repo = task_repo or AgentTaskRepository()
        self.context_repo = context_repo or AgentContextRepository()
        self.proposal_repo = proposal_repo or AgentProposalRepository()
        self.handoff_repo = handoff_repo or AgentHandoffRepository()

    def execute(self, inp: HandoffInput) -> HandoffOutput:
        task = self.task_repo.get_task(inp.task_id)
        steps = self.context_repo.list_task_steps(task.id)

        completed_steps = [
            step
            for step in steps if step["status"] == "completed"
        ]
        pending_steps = [
            step
            for step in steps if step["status"] != "completed"
        ]

        # Latest context snapshot
        context_ref = self.context_repo.get_latest_context_reference(task.id)

        # Open proposals
        open_proposals = self.proposal_repo.list_open_proposals(
            task.id,
            terminal_statuses=list(TERMINAL_PROPOSAL_STATUSES),
        )

        # Build handoff payload
        handoff_payload = {
            "current_status": task.status.value,
            "task_domain": task.task_domain.value,
            "task_type": task.task_type,
            "completed_steps": completed_steps,
            "pending_steps": pending_steps,
            "latest_context_reference": context_ref,
            "open_proposals": open_proposals,
            "open_risks": inp.open_risks or [],
            "recommended_next_actor": inp.to_agent,
            "recommended_next_action": inp.recommended_next_action,
        }

        # Create handoff record
        handoff_id = self.handoff_repo.create_handoff(
            request_id=task.request_id,
            task_id=task.id,
            from_agent=inp.actor.get("agent_id", "system") if inp.actor else "system",
            to_agent=inp.to_agent,
            handoff_reason=inp.handoff_reason,
            handoff_payload=handoff_payload,
        )

        # Timeline event
        self.timeline_service.write_task_escalated_event(
            task=task.id,
            reason=inp.handoff_reason,
            event_source=EventSource.SYSTEM,
            actor=inp.actor,
            escalation_target=inp.to_agent,
        )

        return HandoffOutput(
            task_id=task.id,
            request_id=task.request_id,
            handoff_id=handoff_id,
            handoff_payload=handoff_payload,
        )
