"""
Repositories for Agent Runtime.

Provide a thin Django ORM wrapper so application use cases do not
import ORM models directly.
"""

from typing import Any, Dict, List, Optional

from apps.agent_runtime.domain.entities import AgentProposal, AgentTask
from apps.agent_runtime.infrastructure.models import (
    AgentContextSnapshotModel,
    AgentExecutionRecordModel,
    AgentGuardrailDecisionModel,
    AgentHandoffModel,
    AgentProposalModel,
    AgentTaskModel,
    AgentTaskStepModel,
)


class AgentTaskRepository:
    """AgentTask persistence and query helpers."""

    def create_task(
        self,
        *,
        request_id: str,
        task_domain: str,
        task_type: str,
        input_payload: dict[str, Any],
        created_by: int | None,
        status: str,
        schema_version: str = "v1",
    ) -> AgentTask:
        model = AgentTaskModel._default_manager.create(
            request_id=request_id,
            schema_version=schema_version,
            task_domain=task_domain,
            task_type=task_type,
            status=status,
            input_payload=input_payload,
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by_id=created_by,
        )
        return model.to_domain_entity()

    def get_task(self, task_id: int) -> AgentTask:
        return AgentTaskModel._default_manager.get(pk=task_id).to_domain_entity()

    def list_tasks(
        self,
        *,
        status: str | None = None,
        task_domain: str | None = None,
        task_type: str | None = None,
        requires_human: bool | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        queryset = AgentTaskModel._default_manager.all()
        if status:
            queryset = queryset.filter(status=status)
        if task_domain:
            queryset = queryset.filter(task_domain=task_domain)
        if task_type:
            queryset = queryset.filter(task_type__icontains=task_type)
        if requires_human is not None:
            queryset = queryset.filter(requires_human=requires_human)
        if search:
            queryset = queryset.filter(task_type__icontains=search) | queryset.filter(request_id__icontains=search)

        total_count = queryset.count()
        models = queryset.order_by("-created_at")[offset : offset + limit]
        return {
            "tasks": [model.to_domain_entity() for model in models],
            "total_count": total_count,
        }

    def update_task_state(
        self,
        task_id: int,
        *,
        status: str,
        requires_human: bool | None = None,
    ) -> AgentTask:
        model = AgentTaskModel._default_manager.get(pk=task_id)
        model.status = status
        update_fields = ["status", "updated_at"]
        if requires_human is not None:
            model.requires_human = requires_human
            update_fields.insert(1, "requires_human")
        model.save(update_fields=update_fields)
        return model.to_domain_entity()

    def task_exists(self, task_id: int) -> bool:
        return AgentTaskModel._default_manager.filter(pk=task_id).exists()

    def get_health_summary(self, terminal_statuses: list[str], failed_status: str) -> dict[str, int]:
        total = AgentTaskModel._default_manager.count()
        active = AgentTaskModel._default_manager.exclude(status__in=terminal_statuses).count()
        needs_human = AgentTaskModel._default_manager.filter(requires_human=True).count()
        failed = AgentTaskModel._default_manager.filter(status=failed_status).count()
        return {
            "total_tasks": total,
            "active_tasks": active,
            "needs_human": needs_human,
            "failed_tasks": failed,
        }


class AgentProposalRepository:
    """Proposal and guardrail persistence helpers."""

    def create_proposal(
        self,
        *,
        request_id: str,
        task_id: int | None,
        proposal_type: str,
        status: str,
        risk_level: str,
        approval_required: bool,
        approval_status: str,
        proposal_payload: dict[str, Any],
        approval_reason: str | None,
        created_by: int | None,
        schema_version: str = "v1",
    ) -> AgentProposal:
        model = AgentProposalModel._default_manager.create(
            request_id=request_id,
            schema_version=schema_version,
            task_id=task_id,
            proposal_type=proposal_type,
            status=status,
            risk_level=risk_level,
            approval_required=approval_required,
            approval_status=approval_status,
            proposal_payload=proposal_payload,
            approval_reason=approval_reason,
            created_by_id=created_by,
        )
        return model.to_domain_entity()

    def get_proposal(self, proposal_id: int) -> AgentProposal:
        return AgentProposalModel._default_manager.get(pk=proposal_id).to_domain_entity()

    def update_proposal_status(
        self,
        proposal_id: int,
        *,
        status: str,
        approval_status: str | None = None,
        approval_reason: str | None = None,
    ) -> AgentProposal:
        model = AgentProposalModel._default_manager.get(pk=proposal_id)
        model.status = status
        update_fields = ["status", "updated_at"]
        if approval_status is not None:
            model.approval_status = approval_status
            update_fields.insert(1, "approval_status")
        if approval_reason is not None:
            model.approval_reason = approval_reason
            update_fields.insert(1, "approval_reason")
        model.save(update_fields=update_fields)
        return model.to_domain_entity()

    def create_guardrail_decision(
        self,
        *,
        request_id: str,
        task_id: int | None,
        proposal_id: int | None,
        decision: str,
        reason_code: str,
        message: str,
        evidence: dict[str, Any],
        requires_human: bool,
    ) -> dict[str, Any]:
        model = AgentGuardrailDecisionModel._default_manager.create(
            request_id=request_id,
            task_id=task_id,
            proposal_id=proposal_id,
            decision=decision,
            reason_code=reason_code,
            message=message,
            evidence=evidence,
            requires_human=requires_human,
        )
        return {
            "id": model.id,
            "decision": model.decision,
            "reason_code": model.reason_code,
            "message": model.message,
            "requires_human": model.requires_human,
        }

    def create_execution_record(
        self,
        *,
        request_id: str,
        task_id: int,
        proposal_id: int,
        execution_status: str,
        execution_output: dict[str, Any],
        started_at,
        completed_at,
    ) -> int:
        model = AgentExecutionRecordModel._default_manager.create(
            request_id=request_id,
            task_id=task_id,
            proposal_id=proposal_id,
            execution_status=execution_status,
            execution_output=execution_output,
            started_at=started_at,
            completed_at=completed_at,
        )
        return model.id

    def list_open_proposals(self, task_id: int, terminal_statuses: list[str]) -> list[dict[str, Any]]:
        return list(
            AgentProposalModel._default_manager.filter(task_id=task_id)
            .exclude(status__in=terminal_statuses)
            .values("id", "proposal_type", "status", "risk_level")
        )


class AgentHandoffRepository:
    """Handoff persistence helpers."""

    def create_handoff(
        self,
        *,
        request_id: str,
        task_id: int,
        from_agent: str,
        to_agent: str,
        handoff_reason: str,
        handoff_payload: dict[str, Any],
        handoff_status: str = "completed",
    ) -> int:
        model = AgentHandoffModel._default_manager.create(
            request_id=request_id,
            task_id=task_id,
            from_agent=from_agent,
            to_agent=to_agent,
            handoff_reason=handoff_reason,
            handoff_payload=handoff_payload,
            handoff_status=handoff_status,
        )
        return model.id


class AgentContextRepository:
    """Context snapshot and step query helpers."""

    def get_latest_context_reference(self, task_id: int) -> dict[str, Any] | None:
        snapshot = AgentContextSnapshotModel._default_manager.filter(task_id=task_id).order_by("-created_at").first()
        if snapshot is None:
            return None
        return {
            "snapshot_id": snapshot.id,
            "domain": snapshot.domain,
            "generated_at": snapshot.generated_at.isoformat() if snapshot.generated_at else None,
        }

    def list_task_steps(self, task_id: int) -> list[dict[str, Any]]:
        steps = AgentTaskStepModel._default_manager.filter(task_id=task_id).order_by("step_index")
        return [
            {
                "step_key": step.step_key,
                "step_name": step.step_name,
                "status": step.status,
            }
            for step in steps
        ]
