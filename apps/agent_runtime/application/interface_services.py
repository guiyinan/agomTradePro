"""Application-facing helpers for agent runtime interface pages."""

from __future__ import annotations

from typing import Any

from apps.agent_runtime.application.repository_provider import get_operator_repository


def get_operator_task_list_context(
    *,
    status_filter: str,
    domain_filter: str,
    search: str,
    attention_only: bool,
) -> dict[str, Any]:
    """Build the operator task list page context."""

    repository = get_operator_repository()
    return {
        "page_title": "Agent Runtime Operator",
        "summary": repository.get_summary(),
        "tasks": repository.list_tasks(
            status_filter=status_filter,
            domain_filter=domain_filter,
            search=search,
            attention_only=attention_only,
        ),
        "filters": {
            "status": status_filter,
            "task_domain": domain_filter,
            "search": search,
            "attention": attention_only,
        },
        "status_choices": repository.get_task_status_choices(),
        "domain_choices": repository.get_task_domain_choices(),
    }


def get_task_queryset_for_actor(*, user_id: int | None, is_staff: bool):
    """Return the base task queryset for API object lookups."""

    return get_operator_repository().get_task_queryset(user_id=user_id, is_staff=is_staff)


def get_task_request_id(*, task_id: int) -> str | None:
    """Return one task request id when available."""

    return get_operator_repository().get_task_request_id(task_id)


def get_task_for_actor(*, task_id: Any, user_id: int | None, is_staff: bool):
    """Return one task model subject to actor ownership rules."""

    return get_task_queryset_for_actor(user_id=user_id, is_staff=is_staff).filter(pk=task_id).first()


def get_task_models_by_ids(*, task_ids: list[int]):
    """Return task ORM models for serializer-backed list output."""

    return get_operator_repository().get_task_models_by_ids(task_ids)


def get_task_timeline_events(*, task_id: int):
    """Return timeline events for one task."""

    return get_operator_repository().list_timeline_for_task(task_id)


def get_task_artifacts(*, task_id: int):
    """Return artifacts for one task."""

    return get_operator_repository().list_artifacts_for_task(task_id)


def get_needs_attention_tasks(*, base_queryset: Any, limit: int):
    """Return tasks needing attention plus total count."""

    queryset = base_queryset.filter(requires_human=True) | base_queryset.filter(
        status__in=["needs_human", "failed"]
    )
    queryset = queryset.distinct().order_by("-updated_at")
    total_count = queryset.count()
    return queryset[:limit], total_count


def get_operator_task_detail_context(*, task_id: int) -> dict[str, Any] | None:
    """Build the operator task detail page context."""

    repository = get_operator_repository()
    task = repository.get_task_detail(task_id)
    if task is None:
        return None

    return {
        "page_title": f"Task {task.request_id}",
        "summary": repository.get_summary(),
        "task": task,
        "timeline": list(task.timeline_events.all()),
        "proposals": list(task.proposals.all()),
        "guardrails": list(task.guardrail_decisions.all()),
        "executions": list(task.execution_records.all()),
        "handoffs": list(task.handoffs.all()),
        "latest_context": repository.get_latest_context(task.id),
    }


def get_operator_proposal_list_context(
    *,
    status_filter: str,
    approval_filter: str,
    risk_filter: str,
    search: str,
) -> dict[str, Any]:
    """Build the operator proposal list page context."""

    repository = get_operator_repository()
    return {
        "page_title": "Proposal Approval Queue",
        "summary": repository.get_summary(),
        "proposals": repository.list_proposals(
            status_filter=status_filter,
            approval_filter=approval_filter,
            risk_filter=risk_filter,
            search=search,
        ),
        "filters": {
            "status": status_filter,
            "approval_status": approval_filter,
            "risk_level": risk_filter,
            "search": search,
        },
        "status_choices": repository.get_proposal_status_choices(),
        "approval_choices": repository.get_proposal_approval_choices(),
        "risk_choices": repository.get_proposal_risk_choices(),
    }


def get_operator_proposal_detail_context(*, proposal_id: int) -> dict[str, Any] | None:
    """Build the operator proposal detail page context."""

    repository = get_operator_repository()
    proposal = repository.get_proposal_detail(proposal_id)
    if proposal is None:
        return None

    task_timeline = []
    if proposal.task_id:
        task_timeline = repository.list_timeline_for_task(proposal.task_id)

    return {
        "page_title": f"Proposal {proposal.request_id}",
        "summary": repository.get_summary(),
        "proposal": proposal,
        "guardrails": repository.list_guardrails_for_proposal(proposal.id),
        "executions": repository.list_executions_for_proposal(proposal.id),
        "task_timeline": task_timeline,
    }


def get_proposal_model(*, proposal_id: int):
    """Return one proposal ORM model when available."""

    return get_operator_repository().get_proposal_model(proposal_id)


def get_dashboard_summary_payload() -> dict[str, Any]:
    """Return operator dashboard summary payload."""

    summary = get_operator_repository().get_summary()
    return {
        "task_counts_by_status": summary["task_counts"],
        "proposal_counts_by_status": summary["proposal_counts"],
        "needs_attention_count": summary["needs_attention_count"],
        "total_tasks": summary["total_tasks"],
        "total_proposals": summary["total_proposals"],
    }


def get_dashboard_task_detail_payload(*, task_id: int) -> dict[str, Any] | None:
    """Return operator dashboard task detail payload parts."""

    repository = get_operator_repository()
    task = repository.get_task_detail(task_id)
    if task is None:
        return None
    return {
        "task": task,
        "timeline": repository.list_timeline_for_task(task.id),
        "proposals": repository.list_proposals_for_task(task.id),
        "guardrail_decisions": repository.list_guardrails_for_task(task.id),
        "execution_records": repository.list_executions_for_task(task.id),
    }


def get_dashboard_proposals_payload(*, status_filter: str | None, limit: int, offset: int):
    """Return proposal page plus total count for dashboard API."""

    return get_operator_repository().list_proposals_paginated(
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )


def get_dashboard_guardrails_payload(*, limit: int):
    """Return recent guardrail decisions for dashboard API."""

    return get_operator_repository().list_recent_guardrails(limit=limit)


def get_dashboard_executions_payload(*, limit: int):
    """Return recent execution records for dashboard API."""

    return get_operator_repository().list_recent_executions(limit=limit)
