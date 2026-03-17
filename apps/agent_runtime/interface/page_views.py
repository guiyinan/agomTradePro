from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.agent_runtime.application.proposal_use_cases import (
    ApproveProposalUseCase,
    ExecuteProposalUseCase,
    GuardrailBlockedError,
    InvalidProposalTransitionError,
    RejectProposalUseCase,
    SubmitProposalForApprovalUseCase,
)
from apps.agent_runtime.infrastructure.models import (
    AgentContextSnapshotModel,
    AgentExecutionRecordModel,
    AgentGuardrailDecisionModel,
    AgentHandoffModel,
    AgentProposalModel,
    AgentTaskModel,
    AgentTimelineEventModel,
)


def _ensure_operator_access(request: HttpRequest) -> None:
    user = request.user
    if not user.is_authenticated:
        raise PermissionDenied
    if user.is_staff:
        return
    if user.groups.filter(name="operator").exists():
        return
    raise PermissionDenied


def _build_actor(request: HttpRequest) -> dict[str, Any]:
    return {
        "user_id": request.user.id,
        "is_staff": request.user.is_staff,
        "roles": list(request.user.groups.values_list("name", flat=True)),
    }


def _operator_summary() -> dict[str, Any]:
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


@require_http_methods(["GET"])
def operator_task_list_view(request: HttpRequest) -> HttpResponse:
    _ensure_operator_access(request)

    status_filter = (request.GET.get("status") or "").strip()
    domain_filter = (request.GET.get("task_domain") or "").strip()
    search = (request.GET.get("search") or "").strip()
    attention_only = request.GET.get("attention") == "1"

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

    context = {
        "page_title": "Agent Runtime Operator",
        "summary": _operator_summary(),
        "tasks": tasks[:100],
        "filters": {
            "status": status_filter,
            "task_domain": domain_filter,
            "search": search,
            "attention": attention_only,
        },
        "status_choices": sorted(AgentTaskModel._meta.get_field("status").choices),
        "domain_choices": sorted(AgentTaskModel._meta.get_field("task_domain").choices),
    }
    return render(request, "agent_runtime/operator_task_list.html", context)


@require_http_methods(["GET"])
def operator_task_detail_view(request: HttpRequest, task_id: int) -> HttpResponse:
    _ensure_operator_access(request)

    task = get_object_or_404(
        AgentTaskModel._default_manager.select_related("created_by")
        .prefetch_related(
            Prefetch("timeline_events", queryset=AgentTimelineEventModel._default_manager.order_by("created_at")),
            Prefetch("proposals", queryset=AgentProposalModel._default_manager.order_by("-created_at")),
            Prefetch("guardrail_decisions", queryset=AgentGuardrailDecisionModel._default_manager.order_by("-created_at")),
            Prefetch("execution_records", queryset=AgentExecutionRecordModel._default_manager.order_by("-created_at")),
            Prefetch("handoffs", queryset=AgentHandoffModel._default_manager.order_by("-created_at")),
        ),
        pk=task_id,
    )
    latest_context = (
        AgentContextSnapshotModel._default_manager.filter(task_id=task.id)
        .order_by("-created_at")
        .first()
    )

    context = {
        "page_title": f"Task {task.request_id}",
        "summary": _operator_summary(),
        "task": task,
        "timeline": list(task.timeline_events.all()),
        "proposals": list(task.proposals.all()),
        "guardrails": list(task.guardrail_decisions.all()),
        "executions": list(task.execution_records.all()),
        "handoffs": list(task.handoffs.all()),
        "latest_context": latest_context,
    }
    return render(request, "agent_runtime/operator_task_detail.html", context)


@require_http_methods(["GET"])
def operator_proposal_list_view(request: HttpRequest) -> HttpResponse:
    _ensure_operator_access(request)

    status_filter = (request.GET.get("status") or "").strip()
    approval_filter = (request.GET.get("approval_status") or "").strip()
    risk_filter = (request.GET.get("risk_level") or "").strip()
    search = (request.GET.get("search") or "").strip()

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

    context = {
        "page_title": "Proposal Approval Queue",
        "summary": _operator_summary(),
        "proposals": proposals[:100],
        "filters": {
            "status": status_filter,
            "approval_status": approval_filter,
            "risk_level": risk_filter,
            "search": search,
        },
        "status_choices": sorted(AgentProposalModel._meta.get_field("status").choices),
        "approval_choices": sorted(AgentProposalModel._meta.get_field("approval_status").choices),
        "risk_choices": sorted(AgentProposalModel._meta.get_field("risk_level").choices),
    }
    return render(request, "agent_runtime/operator_proposal_list.html", context)


@require_http_methods(["GET", "POST"])
def operator_proposal_detail_view(request: HttpRequest, proposal_id: int) -> HttpResponse:
    _ensure_operator_access(request)

    proposal = get_object_or_404(
        AgentProposalModel._default_manager.select_related("task", "created_by"),
        pk=proposal_id,
    )

    if request.method == "POST":
        action_name = (request.POST.get("action") or "").strip()
        reason = (request.POST.get("reason") or "").strip() or None
        actor = _build_actor(request)
        try:
            if action_name == "submit":
                SubmitProposalForApprovalUseCase().execute(proposal_id=proposal.id, actor=actor)
                messages.success(request, "Proposal 已提交审批。")
            elif action_name == "approve":
                ApproveProposalUseCase().execute(proposal_id=proposal.id, reason=reason, actor=actor)
                messages.success(request, "Proposal 已批准。")
            elif action_name == "reject":
                RejectProposalUseCase().execute(proposal_id=proposal.id, reason=reason, actor=actor)
                messages.success(request, "Proposal 已拒绝。")
            elif action_name == "execute":
                output = ExecuteProposalUseCase().execute(proposal_id=proposal.id, actor=actor)
                messages.success(request, f"Proposal 已执行，execution_record_id={output.execution_record_id}。")
            else:
                messages.error(request, "不支持的 proposal 动作。")
        except InvalidProposalTransitionError as exc:
            messages.error(request, exc.message)
        except GuardrailBlockedError as exc:
            messages.error(request, f"Guardrail blocked: {exc.guardrail_message}")
        return redirect(reverse("agent_runtime_pages:proposal_detail", args=[proposal.id]))

    guardrails = AgentGuardrailDecisionModel._default_manager.filter(proposal_id=proposal.id).order_by("-created_at")
    executions = AgentExecutionRecordModel._default_manager.filter(proposal_id=proposal.id).order_by("-created_at")
    task_timeline = []
    if proposal.task_id:
        task_timeline = AgentTimelineEventModel._default_manager.filter(task_id=proposal.task_id).order_by("created_at")

    context = {
        "page_title": f"Proposal {proposal.request_id}",
        "summary": _operator_summary(),
        "proposal": proposal,
        "guardrails": guardrails,
        "executions": executions,
        "task_timeline": task_timeline,
    }
    return render(request, "agent_runtime/operator_proposal_detail.html", context)
