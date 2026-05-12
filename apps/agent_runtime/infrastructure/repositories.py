"""
Repositories for Agent Runtime.

Provide a thin Django ORM wrapper so application use cases do not
import ORM models directly.
"""

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Count, Prefetch, Q

from apps.agent_runtime.domain.entities import AgentProposal, AgentTask
from apps.agent_runtime.infrastructure.models import (
    AgentArtifactModel,
    AgentContextSnapshotModel,
    AgentExecutionRecordModel,
    AgentGuardrailDecisionModel,
    AgentHandoffModel,
    AgentProposalModel,
    AgentTaskModel,
    AgentTaskStepModel,
    AgentTimelineEventModel,
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


class AgentRuntimeUserRepository:
    """User lookup helpers needed by agent runtime application services."""

    def get_username_by_id(self, user_id: int) -> str | None:
        """Return a display username for an authenticated user id."""

        user_model = get_user_model()
        username_field = getattr(user_model, "USERNAME_FIELD", "username")
        try:
            user = user_model._default_manager.only(username_field).get(pk=user_id)
        except user_model.DoesNotExist:
            return None
        if hasattr(user, "get_username"):
            return str(user.get_username())
        username = getattr(user, "username", None)
        return str(username) if username else None


class AgentTimelineRepository:
    """Timeline event persistence helpers."""

    def create_event(
        self,
        *,
        request_id: str,
        task_id: int,
        proposal_id: int | None,
        event_type: str,
        event_source: str,
        step_index: int | None,
        event_payload: dict[str, Any],
    ) -> int:
        """Create one timeline event and return its primary key."""

        from apps.agent_runtime.infrastructure.models import AgentTimelineEventModel

        model = AgentTimelineEventModel._default_manager.create(
            request_id=request_id,
            task_id=task_id,
            proposal_id=proposal_id,
            event_type=event_type,
            event_source=event_source,
            step_index=step_index,
            event_payload=event_payload,
        )
        return int(model.id)

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


class AgentOperatorRepository:
    """Read helpers used by agent runtime operator pages."""

    def get_summary(self) -> dict[str, Any]:
        """Return aggregate counts for operator overview cards."""

        task_counts = dict(
            AgentTaskModel._default_manager.values("status")
            .annotate(count=Count("id"))
            .values_list("status", "count")
        )
        proposal_counts = dict(
            AgentProposalModel._default_manager.values("status")
            .annotate(count=Count("id"))
            .values_list("status", "count")
        )
        needs_attention = AgentTaskModel._default_manager.filter(
            Q(requires_human=True) | Q(status__in=["needs_human", "failed"])
        ).distinct()
        return {
            "task_counts": task_counts,
            "proposal_counts": proposal_counts,
            "needs_attention_count": needs_attention.count(),
            "total_tasks": AgentTaskModel._default_manager.count(),
            "total_proposals": AgentProposalModel._default_manager.count(),
        }

    def list_tasks(
        self,
        *,
        status_filter: str = "",
        domain_filter: str = "",
        search: str = "",
        attention_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ):
        """Return task queryset with operator-facing annotations."""

        tasks = (
            AgentTaskModel._default_manager.select_related("created_by")
            .annotate(
                timeline_count=Count("timeline_events", distinct=True),
                proposal_count=Count("proposals", distinct=True),
                guardrail_count=Count("guardrail_decisions", distinct=True),
            )
            .order_by("-created_at")
        )
        if status_filter:
            tasks = tasks.filter(status=status_filter)
        if domain_filter:
            tasks = tasks.filter(task_domain=domain_filter)
        if search:
            tasks = tasks.filter(Q(request_id__icontains=search) | Q(task_type__icontains=search))
        if attention_only:
            tasks = tasks.filter(Q(requires_human=True) | Q(status__in=["needs_human", "failed"]))
        return tasks[offset : offset + limit]

    def get_task_queryset(self, *, user_id: int | None, is_staff: bool):
        """Return base task queryset with ownership filtering."""

        queryset = AgentTaskModel._default_manager.all()
        if not is_staff:
            queryset = queryset.filter(created_by_id=user_id)
        return queryset.order_by("-created_at")

    def get_task_request_id(self, task_id: int) -> str | None:
        """Return one task request_id when available."""

        task_model = AgentTaskModel._default_manager.filter(pk=task_id).only("request_id").first()
        rid = getattr(task_model, "request_id", None)
        return rid if isinstance(rid, str) else None

    def get_task_models_by_ids(self, task_ids: list[int]):
        """Return task ORM models by ids."""

        return AgentTaskModel._default_manager.filter(id__in=task_ids)

    def get_task_status_choices(self) -> list[tuple[str, str]]:
        """Return task status filter choices."""

        return sorted(AgentTaskModel._meta.get_field("status").choices)

    def get_task_domain_choices(self) -> list[tuple[str, str]]:
        """Return task domain filter choices."""

        return sorted(AgentTaskModel._meta.get_field("task_domain").choices)

    def get_task_detail(self, task_id: int):
        """Return one task with related operator data prefetched."""

        return (
            AgentTaskModel._default_manager.select_related("created_by")
            .prefetch_related(
                Prefetch("timeline_events", queryset=AgentTimelineEventModel._default_manager.order_by("created_at")),
                Prefetch("proposals", queryset=AgentProposalModel._default_manager.order_by("-created_at")),
                Prefetch(
                    "guardrail_decisions",
                    queryset=AgentGuardrailDecisionModel._default_manager.order_by("-created_at"),
                ),
                Prefetch(
                    "execution_records",
                    queryset=AgentExecutionRecordModel._default_manager.order_by("-created_at"),
                ),
                Prefetch("handoffs", queryset=AgentHandoffModel._default_manager.order_by("-created_at")),
            )
            .filter(pk=task_id)
            .first()
        )

    def get_latest_context(self, task_id: int):
        """Return the latest context snapshot for a task."""

        return (
            AgentContextSnapshotModel._default_manager.filter(task_id=task_id)
            .order_by("-created_at")
            .first()
        )

    def list_proposals(
        self,
        *,
        status_filter: str = "",
        approval_filter: str = "",
        risk_filter: str = "",
        search: str = "",
        limit: int = 100,
    ):
        """Return proposal queryset for the operator queue."""

        proposals = AgentProposalModel._default_manager.select_related("task", "created_by").order_by("-created_at")
        if status_filter:
            proposals = proposals.filter(status=status_filter)
        if approval_filter:
            proposals = proposals.filter(approval_status=approval_filter)
        if risk_filter:
            proposals = proposals.filter(risk_level=risk_filter)
        if search:
            proposals = proposals.filter(
                Q(request_id__icontains=search)
                | Q(proposal_type__icontains=search)
                | Q(task__request_id__icontains=search)
        )
        return proposals[:limit]

    def list_proposals_for_task(self, task_id: int):
        """Return proposals linked to one task."""

        return AgentProposalModel._default_manager.filter(task_id=task_id).order_by("-created_at")

    def get_proposal_status_choices(self) -> list[tuple[str, str]]:
        """Return proposal status filter choices."""

        return sorted(AgentProposalModel._meta.get_field("status").choices)

    def get_proposal_approval_choices(self) -> list[tuple[str, str]]:
        """Return proposal approval filter choices."""

        return sorted(AgentProposalModel._meta.get_field("approval_status").choices)

    def get_proposal_risk_choices(self) -> list[tuple[str, str]]:
        """Return proposal risk filter choices."""

        return sorted(AgentProposalModel._meta.get_field("risk_level").choices)

    def get_proposal_detail(self, proposal_id: int):
        """Return one proposal with linked task and creator."""

        return (
            AgentProposalModel._default_manager.select_related("task", "created_by")
            .filter(pk=proposal_id)
            .first()
        )

    def list_guardrails_for_proposal(self, proposal_id: int):
        """Return guardrail decisions for one proposal."""

        return AgentGuardrailDecisionModel._default_manager.filter(proposal_id=proposal_id).order_by("-created_at")

    def list_executions_for_proposal(self, proposal_id: int):
        """Return execution records for one proposal."""

        return AgentExecutionRecordModel._default_manager.filter(proposal_id=proposal_id).order_by("-created_at")

    def list_guardrails_for_task(self, task_id: int):
        """Return guardrail decisions for one task."""

        return AgentGuardrailDecisionModel._default_manager.filter(task_id=task_id).order_by("-created_at")

    def list_executions_for_task(self, task_id: int):
        """Return execution records for one task."""

        return AgentExecutionRecordModel._default_manager.filter(task_id=task_id).order_by("-created_at")

    def list_timeline_for_task(self, task_id: int):
        """Return timeline events for one task."""

        return AgentTimelineEventModel._default_manager.filter(task_id=task_id).order_by("created_at")

    def list_artifacts_for_task(self, task_id: int):
        """Return task artifacts ordered newest first."""

        return AgentArtifactModel._default_manager.filter(task_id=task_id).order_by("-created_at")

    def get_proposal_model(self, proposal_id: int):
        """Return one proposal ORM model when available."""

        return AgentProposalModel._default_manager.filter(pk=proposal_id).first()

    def list_proposals_paginated(
        self,
        *,
        status_filter: str | None,
        limit: int,
        offset: int,
    ):
        """Return proposal queryset page plus total count."""

        queryset = AgentProposalModel._default_manager.all()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        total = queryset.count()
        return queryset.order_by("-created_at")[offset : offset + limit], total

    def list_recent_guardrails(self, *, limit: int):
        """Return recent guardrail decisions."""

        return AgentGuardrailDecisionModel._default_manager.order_by("-created_at")[:limit]

    def list_recent_executions(self, *, limit: int):
        """Return recent execution records."""

        return AgentExecutionRecordModel._default_manager.order_by("-created_at")[:limit]
