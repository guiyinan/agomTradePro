"""
Repositories for Agent Runtime.

Provide a thin Django ORM wrapper so application use cases do not
import ORM models directly.
"""

import json
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Count, Prefetch, Q, QuerySet

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
from apps.audit.domain.entities import mask_sensitive_params, mask_sensitive_text

_MAX_AGENT_EVIDENCE_BYTES = 1_048_576


def _sanitize_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Detach, redact, and bound JSON evidence before ORM persistence."""

    masked = mask_sensitive_params(payload)
    if not isinstance(masked, dict):
        raise ValueError("agent_evidence_payload_invalid")
    try:
        encoded = json.dumps(
            masked,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            cls=DjangoJSONEncoder,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("agent_evidence_payload_invalid") from exc
    if len(encoded) > _MAX_AGENT_EVIDENCE_BYTES:
        raise ValueError("agent_evidence_payload_too_large")
    detached = json.loads(encoded.decode("utf-8"))
    if not isinstance(detached, dict):
        raise ValueError("agent_evidence_payload_invalid")
    return cast(dict[str, Any], detached)


def _nonnegative_int(value: object, *, field_name: str) -> int:
    """Validate one exact non-negative integer from a dynamic execution boundary."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name}_invalid")
    return value


def _nonnegative_decimal(value: object, *, field_name: str) -> Decimal:
    """Validate one finite non-negative decimal from execution evidence."""

    if isinstance(value, bool) or not isinstance(value, int | float | Decimal | str):
        raise ValueError(f"{field_name}_invalid")
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name}_invalid") from exc
    if not normalized.is_finite() or normalized < 0:
        raise ValueError(f"{field_name}_invalid")
    return normalized


def _flat_string_choices(choices: object) -> list[tuple[str, str]]:
    """Normalize flat Django field choices for interface filters."""

    if not isinstance(choices, (list, tuple)):
        return []
    normalized: list[tuple[str, str]] = []
    for item in choices:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        value, label = item
        if isinstance(label, str):
            normalized.append((str(value), label))
    return sorted(normalized)


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

    def update_task_state(
        self,
        task_id: int,
        *,
        status: str,
        requires_human: bool | None = None,
    ) -> AgentTask:
        """Persist a task lifecycle transition and return the updated entity."""

        model = AgentTaskModel._default_manager.get(pk=task_id)
        model.status = status
        update_fields = ["status", "updated_at"]
        if requires_human is not None:
            model.requires_human = requires_human
            update_fields.insert(1, "requires_human")
        model.save(update_fields=update_fields)
        return model.to_domain_entity()

    def task_exists(self, task_id: int) -> bool:
        """Return whether a task exists."""

        return AgentTaskModel._default_manager.filter(pk=task_id).exists()

    def get_health_summary(
        self,
        terminal_statuses: list[str],
        failed_status: str,
    ) -> dict[str, int]:
        """Return aggregate task lifecycle health counters."""

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
            queryset = queryset.filter(task_type__icontains=search) | queryset.filter(
                request_id__icontains=search
            )

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
            event_payload=_sanitize_evidence(event_payload),
        )
        return int(model.id)


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
            approval_reason=(
                mask_sensitive_text(approval_reason)[:2_000] if approval_reason else None
            ),
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
            message=mask_sensitive_text(message)[:2_000],
            evidence=_sanitize_evidence(evidence),
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
        task_id: int | None,
        proposal_id: int,
        execution_status: str,
        execution_output: dict[str, Any],
        started_at: datetime,
        completed_at: datetime,
    ) -> int:
        from django.conf import settings

        if settings.DECISION_SNAPSHOT_REQUIRED:
            snapshot_id = str(execution_output.get("decision_input_snapshot_id") or "")
            from core.integration.research_integrity_registry import get_decision_snapshot

            snapshot = get_decision_snapshot(snapshot_id) if snapshot_id else None
            if snapshot is None or snapshot.must_not_use:
                raise ValueError("agent execution requires a valid decision input snapshot")
        if settings.PROMPT_EVAL_GATE_ENABLED:
            required = (
                "prompt_version_id",
                "model_version",
                "output_schema_version",
                "eval_baseline_id",
            )
            missing = [field for field in required if not execution_output.get(field)]
            if missing:
                raise ValueError(f"agent execution lacks prompt evidence: {', '.join(missing)}")
            from core.integration.research_integrity_registry import (
                is_prompt_version_active,
            )

            if not is_prompt_version_active(execution_output["prompt_version_id"]):
                raise ValueError("agent execution prompt version is not active")
        safe_execution_output = _sanitize_evidence(execution_output)
        actual_tokens = _nonnegative_int(
            safe_execution_output.get("actual_tokens", 0),
            field_name="actual_tokens",
        )
        actual_cost = _nonnegative_decimal(
            safe_execution_output.get("actual_cost", 0),
            field_name="actual_cost",
        )
        model = AgentExecutionRecordModel._default_manager.create(
            request_id=request_id,
            task_id=task_id,
            proposal_id=proposal_id,
            execution_status=execution_status,
            execution_output=safe_execution_output,
            started_at=started_at,
            completed_at=completed_at,
            prompt_version_id=str(safe_execution_output.get("prompt_version_id") or ""),
            model_version=str(safe_execution_output.get("model_version") or ""),
            output_schema_version=str(safe_execution_output.get("output_schema_version") or ""),
            eval_baseline_id=str(safe_execution_output.get("eval_baseline_id") or ""),
            decision_input_snapshot_id=str(
                safe_execution_output.get("decision_input_snapshot_id") or ""
            ),
            actual_tokens=actual_tokens,
            actual_cost=actual_cost,
        )
        return int(model.id)

    def list_open_proposals(
        self, task_id: int, terminal_statuses: list[str]
    ) -> list[dict[str, Any]]:
        rows = (
            AgentProposalModel._default_manager.filter(task_id=task_id)
            .exclude(status__in=terminal_statuses)
            .values("id", "proposal_type", "status", "risk_level")
        )
        return [dict(row) for row in rows]


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
            handoff_reason=mask_sensitive_text(handoff_reason)[:2_000],
            handoff_payload=_sanitize_evidence(handoff_payload),
            handoff_status=handoff_status,
        )
        return model.id


class AgentContextRepository:
    """Context snapshot and step query helpers."""

    def get_latest_context_reference(self, task_id: int) -> dict[str, Any] | None:
        snapshot = (
            AgentContextSnapshotModel._default_manager.filter(task_id=task_id)
            .order_by("-created_at")
            .first()
        )
        if snapshot is None:
            return None
        return {
            "snapshot_id": snapshot.id,
            "domain": snapshot.domain,
            "generated_at": snapshot.generated_at.isoformat() if snapshot.generated_at else None,
            "decision_input_snapshot_id": snapshot.decision_input_snapshot_id or None,
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
            Counter(AgentTaskModel._default_manager.values_list("status", flat=True).iterator())
        )
        proposal_counts = dict(
            Counter(AgentProposalModel._default_manager.values_list("status", flat=True).iterator())
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
    ) -> QuerySet[AgentTaskModel]:
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

    def get_task_queryset(
        self,
        *,
        user_id: int | None,
        is_staff: bool,
    ) -> QuerySet[AgentTaskModel]:
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

    def get_task_models_by_ids(self, task_ids: list[int]) -> QuerySet[AgentTaskModel]:
        """Return task ORM models by ids."""

        return AgentTaskModel._default_manager.filter(id__in=task_ids)

    def get_task_status_choices(self) -> list[tuple[str, str]]:
        """Return task status filter choices."""

        return _flat_string_choices(AgentTaskModel._meta.get_field("status").choices)

    def get_task_domain_choices(self) -> list[tuple[str, str]]:
        """Return task domain filter choices."""

        return _flat_string_choices(AgentTaskModel._meta.get_field("task_domain").choices)

    def get_task_detail(self, task_id: int) -> AgentTaskModel | None:
        """Return one task with related operator data prefetched."""

        return (
            AgentTaskModel._default_manager.select_related("created_by")
            .prefetch_related(
                Prefetch(
                    "timeline_events",
                    queryset=AgentTimelineEventModel._default_manager.order_by("created_at"),
                ),
                Prefetch(
                    "proposals",
                    queryset=AgentProposalModel._default_manager.order_by("-created_at"),
                ),
                Prefetch(
                    "guardrail_decisions",
                    queryset=AgentGuardrailDecisionModel._default_manager.order_by("-created_at"),
                ),
                Prefetch(
                    "execution_records",
                    queryset=AgentExecutionRecordModel._default_manager.order_by("-created_at"),
                ),
                Prefetch(
                    "handoffs", queryset=AgentHandoffModel._default_manager.order_by("-created_at")
                ),
            )
            .filter(pk=task_id)
            .first()
        )

    def get_latest_context(self, task_id: int) -> AgentContextSnapshotModel | None:
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
    ) -> QuerySet[AgentProposalModel]:
        """Return proposal queryset for the operator queue."""

        proposals = AgentProposalModel._default_manager.select_related(
            "task", "created_by"
        ).order_by("-created_at")
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

    def list_proposals_for_task(self, task_id: int) -> QuerySet[AgentProposalModel]:
        """Return proposals linked to one task."""

        return AgentProposalModel._default_manager.filter(task_id=task_id).order_by("-created_at")

    def get_proposal_status_choices(self) -> list[tuple[str, str]]:
        """Return proposal status filter choices."""

        return _flat_string_choices(AgentProposalModel._meta.get_field("status").choices)

    def get_proposal_approval_choices(self) -> list[tuple[str, str]]:
        """Return proposal approval filter choices."""

        return _flat_string_choices(AgentProposalModel._meta.get_field("approval_status").choices)

    def get_proposal_risk_choices(self) -> list[tuple[str, str]]:
        """Return proposal risk filter choices."""

        return _flat_string_choices(AgentProposalModel._meta.get_field("risk_level").choices)

    def get_proposal_detail(self, proposal_id: int) -> AgentProposalModel | None:
        """Return one proposal with linked task and creator."""

        return (
            AgentProposalModel._default_manager.select_related("task", "created_by")
            .filter(pk=proposal_id)
            .first()
        )

    def list_guardrails_for_proposal(
        self,
        proposal_id: int,
    ) -> QuerySet[AgentGuardrailDecisionModel]:
        """Return guardrail decisions for one proposal."""

        return AgentGuardrailDecisionModel._default_manager.filter(
            proposal_id=proposal_id
        ).order_by("-created_at")

    def list_executions_for_proposal(
        self,
        proposal_id: int,
    ) -> QuerySet[AgentExecutionRecordModel]:
        """Return execution records for one proposal."""

        return AgentExecutionRecordModel._default_manager.filter(proposal_id=proposal_id).order_by(
            "-created_at"
        )

    def list_guardrails_for_task(
        self,
        task_id: int,
    ) -> QuerySet[AgentGuardrailDecisionModel]:
        """Return guardrail decisions for one task."""

        return AgentGuardrailDecisionModel._default_manager.filter(task_id=task_id).order_by(
            "-created_at"
        )

    def list_executions_for_task(
        self,
        task_id: int,
    ) -> QuerySet[AgentExecutionRecordModel]:
        """Return execution records for one task."""

        return AgentExecutionRecordModel._default_manager.filter(task_id=task_id).order_by(
            "-created_at"
        )

    def list_timeline_for_task(self, task_id: int) -> QuerySet[AgentTimelineEventModel]:
        """Return timeline events for one task."""

        return AgentTimelineEventModel._default_manager.filter(task_id=task_id).order_by(
            "created_at"
        )

    def list_artifacts_for_task(self, task_id: int) -> QuerySet[AgentArtifactModel]:
        """Return task artifacts ordered newest first."""

        return AgentArtifactModel._default_manager.filter(task_id=task_id).order_by("-created_at")

    def get_proposal_model(self, proposal_id: int) -> AgentProposalModel | None:
        """Return one proposal ORM model when available."""

        return AgentProposalModel._default_manager.filter(pk=proposal_id).first()

    def list_proposals_paginated(
        self,
        *,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> tuple[QuerySet[AgentProposalModel], int]:
        """Return proposal queryset page plus total count."""

        queryset = AgentProposalModel._default_manager.all()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        total = queryset.count()
        return queryset.order_by("-created_at")[offset : offset + limit], total

    def list_recent_guardrails(
        self,
        *,
        limit: int,
    ) -> QuerySet[AgentGuardrailDecisionModel]:
        """Return recent guardrail decisions."""

        return AgentGuardrailDecisionModel._default_manager.order_by("-created_at")[:limit]

    def list_recent_executions(
        self,
        *,
        limit: int,
    ) -> QuerySet[AgentExecutionRecordModel]:
        """Return recent execution records."""

        return AgentExecutionRecordModel._default_manager.order_by("-created_at")[:limit]
